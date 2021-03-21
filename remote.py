import asyncio
import struct
import traceback
import argparse
import aiosqlite
import logging
import time
import threading

from enum import Enum
readMode = Enum('READ_MOD', ('EXACT','LINE','MAX','UNTIL'))#读的模式

class MyError(Exception):
    pass

MAX_TOKEN = 200000 #令牌桶最大容量
tokenLock = asyncio.Lock()

bandwidthLimit = dict() #用户的流量限制
curAvailToken = dict() #用户当前可使用的流量
lastUseTime = dict() #用户上次使用令牌桶的时间


#流量控制
async def ControlBandwidth(username, requirement):
    while(True):
        #tokenLock.acquire()
        async with tokenLock:
            curTime = time.time() #获取当前时间
        
            #计算从上次发送到这次发送，新发放的令牌数量
            increment = (curTime - lastUseTime[username]) * bandwidthLimit[username] * 1000
            #更新令牌桶的数量
            if((curAvailToken[username] + increment) > MAX_TOKEN):
                curAvailToken[username] = MAX_TOKEN
            else:
                curAvailToken[username] = curAvailToken[username] + increment
            
            lastUseTime[username] = curTime #更新使用时间
        
            if(curAvailToken[username] >= requirement):#令牌数量足够，可以转发数据
                curAvailToken[username] -= requirement
                log.debug(f'User {username} is allowed to send message ({requirement} Bytes) now.')
                #tokenLock.release()
                return
            else:
                #tokenLock.release()
                log.debug(f'User {username} is not allowed to send message now.')
                log.debug(f'Available Bandwidth: {curAvailToken[username]}. Require: {requirement} ')
                time.sleep(1)  

#异步读取
async def aioRead(reader, mode, *, errHint = None, exactData=None, exactLen = None, maxLen = -1, dataSeparator = b'\r\n'):
    readData = None
    try:
        if mode == readMode.EXACT:#精确读取exactLen个bytes
            exactLen = len(exactData) if exactData else exactLen
            readData = await reader.readexactly(exactLen)
            if exactData and readData != exactData:
                raise MyError(f'Error {errHint} = {readData} correct = {exactData}')
        
        elif mode == readMode.LINE:#读取一行
            readData = await reader.readline()
            
        elif mode == readMode.MAX:#至多读取maxLen个byte
            readData = await reader.read(maxLen)
            
        elif mode == readMode.UNTIL:#从流中读取数据直至遇到readSeparator
            readData = await reader.readuntil(dataSeparator)
        else:
            raise MyError(f'Error mode = {mode}')
        
    except Exception as exc:
        traceback.print_exc()
        raise exc
    else:
        if not readData:
            raise MyError(f'EOF when reading {errHint}')
        return readData

#异步写入        
async def aioWrite(writer, writeData, *, errHint = None):
    try:
        writer.write(writeData)
        await writer.drain()
    except Exception as exc:
        traceback.print_exc()
        raise MyError(f'err = {errHint}')

#中继转发信息
async def Proxy(reader,writer,username):
    try:
        while(1):
            data = await aioRead(reader, readMode.MAX, maxLen=65535, errHint='Proxy Data')
            log.debug(f'Received: {data!r}')
            if(len(data) == 0):
                log.info("connection is ended")
                return
            
            #发送之前先进行限流操作
            await ControlBandwidth(username, len(data))
            
            log.debug(f'Send: {data!r}')
            await aioWrite(writer,data)
            
    except Exception as exc:
        traceback.print_exc()


async def RemoteHandleSocks5(remoteToLocalReader, remoteToLocalWriter, username):
    try:
        #接收客户请求
        recvData = await aioRead(remoteToLocalReader, readMode.MAX, maxLen=256)
        log.debug(f'Receive from local: {recvData!r}')

        if(len(recvData) > 4):
            ver,cmd,rsv,atyp = struct.unpack("!BBBB",recvData[0:4])
            if (cmd == 0x01):#CONNECT请求
                if(atyp == 0x01):#ipv4
                    addrlen = 4
                    boundAddr = (recvData[4:8]).decode()
                    boundPort = struct.unpack("!H",recvData[8:10])[0]

                elif(atyp == 0x03):#domain
                    addrlen = int(recvData[4])
                    boundAddr = (recvData[5:5+addrlen]).decode()
                    boundPort = struct.unpack("!H",recvData[-2:])[0]

                else:#ipv6
                    addrlen = 16
                    boundAddr = (recvData[4:20]).decode()
                    boundPort = struct.unpack("!H",recvData[20:22])[0]
                
                #连接目标服务端
                remoteToDestReader, remoteToDestWriter = await asyncio.open_connection(boundAddr, boundPort)

                #构造响应内容，响应结束后就可以进行收发数据
                response = 0x00
                writeData = bytes([0x05, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
                log.debug(f'Send to local: {writeData!r}')
                #发送之前先进行限流操作
                await ControlBandwidth(username, len(writeData))
                await aioWrite(remoteToLocalWriter, writeData)

                #转发数据,中继
                await asyncio.gather(
                    Proxy(remoteToLocalReader, remoteToDestWriter, username), Proxy(remoteToDestReader, remoteToLocalWriter, username), return_exceptions = True)


            else:#不是connect请求不处理
                return
        else:#长度不够
            return
    except Exception as exc:
        traceback.print_exc()


async def RemoteHandleHTTP(remoteToLocalReader, remoteToLocalWriter, username):
    try:
        await aioRead(remoteToLocalReader, readMode.EXACT, exactData = b'CONNECT',errHint = 'method')
        await aioRead(remoteToLocalReader, readMode.EXACT, exactLen = 1)#skip ' '
        
        #read dstAddr
        dstAddr = await aioRead(remoteToLocalReader, readMode.UNTIL, dataSeparator= b':')
        dstAddr = dstAddr[0:-1].decode() #ignore the last character ':'
        
        #read dstPort
        dstPort = 0
        while(1):
            readNum = await aioRead(remoteToLocalReader, readMode.EXACT, exactLen = 1)
            if(readNum[0] == 32):#空格
                break
            dstPort = (dstPort * 10) + readNum[0] - 48
        
        await aioRead(remoteToLocalReader, readMode.EXACT, exactData = b'HTTP/', errHint = 'HTTP/')
        version = await aioRead(remoteToLocalReader, readMode.EXACT, exactLen=3)
        version = version.decode()

        await aioRead(remoteToLocalReader,readMode.MAX, maxLen=1024, errHint='rest part of http request')#读完剩余的部分
        
        #连接目的
        remoteToDestReader, remoteToDestWriter = await asyncio.open_connection(dstAddr, dstPort)
        log.info(f'Establish connection to web {dstAddr!r} {dstPort!r}')
        
        #发送响应给local
        writeData = 'HTTP/' + version + ' 200 ' + 'Connection established\r\n\r\n'
        log.debug(f"Send: {writeData!r} to localProxy")
        #发送之前先进行限流操作
        await ControlBandwidth(username, len(writeData))
        await aioWrite(remoteToLocalWriter, writeData.encode(), errHint ='reply to client')
        
        #转发数据,中继
        await asyncio.gather(Proxy(remoteToLocalReader, remoteToDestWriter, username), Proxy(remoteToDestReader, remoteToLocalWriter, username), return_exceptions=True)
    
    except Exception as exc:
        traceback.print_exc()


userPwd = dict()
userLock = asyncio.Lock()

async def databaseTask():
    async with aiosqlite.connect('user.db') as db:
        while True:
            await asyncio.sleep(1)
            userDict = dict()
            sqlQuery = "SELECT username,password,bandwidth FROM users"
            async with db.execute(sqlQuery) as cursor:
                async for row in cursor:
                    if row[0] not in curAvailToken:#该用户之前没加过
                        async with tokenLock:
                            curAvailToken[row[0]] = 0
                            lastUseTime[row[0]] = time.time()
                    bandwidthLimit[row[0]] = row[2]#带宽限制
                    userDict[row[0]] = row[1]#密码
            
            async with userLock:
                global userPwd
                userPwd = userDict

async def proxyTask():
    remoteServer = await asyncio.start_server(
        CommunicateLocalServer, arg.remoteHost, arg.remotePort)
    addrList = list([s.getsockname() for s in remoteServer.sockets])
    log.info(f'LISTEN {addrList}')

    async with remoteServer:
        await remoteServer.serve_forever()

async def CommunicateLocalServer(remoteToLocalReader, remoteToLocalWriter):
    proxyType = await aioRead(remoteToLocalReader, readMode.MAX, maxLen = 1)
    if(len(proxyType) == 0):
        return

    #read username
    await aioRead(remoteToLocalReader, readMode.EXACT, exactData=b"username=", errHint="username")
    usrName = await aioRead(remoteToLocalReader, readMode.UNTIL, dataSeparator=b';')
    usrName = usrName[0:-1].decode()
    #read password
    await aioRead(remoteToLocalReader, readMode.EXACT, exactData=b"password=", errHint="password")
    pwd = await aioRead(remoteToLocalReader, readMode.UNTIL, dataSeparator=b';')
    pwd = pwd[0:-1].decode()
    
    #check usrname and password
    isMatch = False
    global userPwd
    if usrName in userPwd:
        if userPwd[usrName] == pwd:
            isMatch = True
    if(not isMatch):
        log.info("Wrong password or the user does not exist!")
        return
    
    proxyType = proxyType.decode()
    if(proxyType == 'S'):#socks5
        await RemoteHandleSocks5(remoteToLocalReader, remoteToLocalWriter, usrName)
    else:#http
        await RemoteHandleHTTP(remoteToLocalReader, remoteToLocalWriter, usrName)


async def main():
    asyncio.create_task(proxyTask())
    asyncio.create_task(databaseTask())
    
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)
    
    _parser = argparse.ArgumentParser(description='remote proxy')
    _parser.add_argument("-rh","--remoteHost", dest="remoteHost", default="127.0.0.1", help="remote proxy host")
    _parser.add_argument("-rp","--remotePort", dest="remotePort", type=int, default=8000, help="remote proxy port")
    _parser.add_argument("-l","--level", dest="debugLevel",type=int, default=1, choices=range(1,6), help="debug level, range from 1 to 5")
    
    arg = _parser.parse_args()
    
    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(arg.debugLevel * 10)

    log.info(f'{arg}')

    asyncio.run(main())