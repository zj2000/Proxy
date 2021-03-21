import asyncio
import struct
import traceback
import argparse
import logging
import websockets
import time
import sys

from enum import Enum
readMode = Enum('READ_MOD', ('EXACT','LINE','MAX','UNTIL'))#读的模式

class MyError(Exception):
    pass

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
async def Proxy(reader,writer,state):
    global totRecv
    global totSend
    try:
        while(1):
            data = await aioRead(reader, readMode.MAX, maxLen=65535, errHint='Proxy Data')
            print(f'Received: {data!r}')
            if(len(data) == 0):
                return
            
            if state == "R":
                totRecv += len(data)
            else:
                totSend += len(data)    
            
            log.debug(f'Send: {data!r}')
            await aioWrite(writer,data)
            
    except Exception as exc:
        traceback.print_exc()

#HTTP
async def LocalHandleHTTP(localToClientReader,localToClientWriter):
    try:
        recvCMD = await aioRead(localToClientReader, readMode.MAX, maxLen = 1024, errHint = 'local recv client CMD')
        recvCMD = recvCMD.decode()
        
        #recvData = "Husername=%s;password=%s;"%arg.username%arg.password
        recvData = 'H'+"username=" + arg.username + ";password=" + arg.password + ';'#用户名和密码
        recvData += 'C' + recvCMD
        
        recvData = recvData.encode()
        
        #连接remoteProxy
        localToRemoteReader, localToRemoteWriter = await asyncio.open_connection(arg.remoteHost, arg.remotePort)
        log.debug(f'Establish connection to remoteProxy {arg.remoteHost!r} {arg.remotePort!r}')
        
        #转发CMD给remoteProxy
        await aioWrite(localToRemoteWriter, recvData, errHint='client CMD')
        log.debug(f'send to remoteRroxy: {recvData!r}')
        
        #接受remoteProxy的响应并转发回客户
        recvData = await aioRead(localToRemoteReader, readMode.MAX, maxLen = 256, errHint = 'read CMD response')
        log.debug(f'Receive from remote: {recvData!r}')
        
        await aioWrite(localToClientWriter, recvData, errHint='CMD response')
        log.debug(f'send to client: {recvData!r}')
        
        #转发数据,中继
        await asyncio.gather(Proxy(localToClientReader, localToRemoteWriter, "S"), Proxy(localToRemoteReader, localToClientWriter, "R"), return_exceptions=True)
    
    except Exception as exc:
        traceback.print_exc()


#socks5--处理客户端的认证请求
async def LocalHandleSocks5(localToClientReader,localToClientWriter):
    try:
        #握手认证过程
        recvData = await aioRead(localToClientReader, readMode.MAX, maxLen=256)
        log.debug(f'Received: {recvData!r}')

        serverVer = 0x05
        serverMethod = 0x00
        writeData = struct.pack("!BB",serverVer,serverMethod)
        log.debug(f'Send: {writeData!r}')
        await aioWrite(localToClientWriter, writeData)
        
        
        #接收客户请求CMD
        recvData = await aioRead(localToClientReader, readMode.MAX, maxLen=256)
        log.debug(f'Receive from client: {recvData!r}')
        
        #连接remoteProxy
        localToRemoteReader, localToRemoteWriter = await asyncio.open_connection(arg.remoteHost, arg.remotePort)
        log.debug(f'Establish connection to remoteProxy {arg.remoteHost!r} {arg.remotePort!r}')
        
        auth = 'S' + "username=" + arg.username + ";password=" + arg.password + ';'#用户名和密码
        auth = auth.encode()
        recvData = auth + recvData
        #recvData = b'S' + recvData

        #转发CMD给remoteProxy
        await aioWrite(localToRemoteWriter, recvData, errHint='client CMD')
        log.debug(f'send to remoteRroxy: {recvData!r}')
        
        #接受remoteProxy的响应并转发回客户
        recvData = await aioRead(localToRemoteReader, readMode.MAX, maxLen = 256)
        log.debug(f'Receive from remote: {recvData!r}')
        
        await aioWrite(localToClientWriter, recvData, errHint='CMD response')
        log.debug(f'send to client: {recvData!r}')
        
        #转发数据,中继
        await asyncio.gather(Proxy(localToClientReader, localToRemoteWriter, "S"), Proxy(localToRemoteReader, localToClientWriter,"R"), return_exceptions=True)
    
    except Exception as exc:
        traceback.print_exc()


async def CommunicateClient(myReader,myWriter):
    firstData = await aioRead(myReader, readMode.MAX,maxLen = 1)
    if(len(firstData) == 0):
        return
    
    if(firstData[0] == 0x05):#socks5
        await LocalHandleSocks5(myReader,myWriter)
    elif(firstData.decode() == 'C'):#HTTP
        await LocalHandleHTTP(myReader,myWriter)
    else:
        return

totSend = 0#发送带宽
totRecv = 0#接收带宽
lastUpdateTime = 0

async def HandleWebsocket(websocket, path):
    global totSend
    global totRecv
    global lastUpdateTime
    
    recv = await websocket.recv()
    log.debug(f"Receive: {recv}")
    
    lastUpdateTime = time.time()
    sendBandwidth = 0
    recvBandwidth = 0
    
    try:
        while True:
            curTime = time.time()
            dalta = curTime - lastUpdateTime
            if dalta != 0:
                recvBandwidth = totRecv / dalta
                sendBandwidth = totSend / dalta
                totRecv = 0
                totSend = 0
                lastUpdateTime = curTime
                
            sendStr = str(sendBandwidth) + " " + str(recvBandwidth)
            await websocket.send(sendStr)
            
            #recv = await websocket.recv()
            await asyncio.sleep(1)
            
    except websockets.exceptions.ConnectionClosedError as exc:
        log.error(f'{exc}')
    except websockets.exceptions.ConnectionClosedOK as exc:
        log.error(f'{exc}')
    except Exception:
        log.error(f'{traceback.format_exc()}')
        exit(1)
        

async def localTask():
    websocketServer = await websockets.serve(HandleWebsocket, "127.0.0.1", arg.websocketPort)
    log.info(f"Websocket listen {websocketServer.sockets[0].getsockname()}")
    
    localServer = await asyncio.start_server(
        CommunicateClient, arg.localHost, arg.localPort)
    async with localServer:
        await localServer.serve_forever()

async def main():
    asyncio.create_task(localTask())
    
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)
    
    _parser = argparse.ArgumentParser(description='local proxy')
    _parser.add_argument("-lh","--localHost", dest="localHost", default="127.0.0.1", help="local proxy host")
    _parser.add_argument("-lp", "--localPort", dest="localPort", default=8888, type=int, required=True, help="local proxy port")
    _parser.add_argument("-rh","--remoteHost", dest="remoteHost", default="127.0.0.1", help="remote proxy host")
    _parser.add_argument("-rp", "--remotePort", dest="remotePort", default=8000, type=int, help="remote proxy port")
    _parser.add_argument("-l","--level", dest="debugLevel", type=int, default=1, choices=range(1,6), help="debug level, range from 1 to 5")
    _parser.add_argument("-wsp","--websocketPort", dest="websocketPort", type=int, default=9000, help="websocket port")
    _parser.add_argument("username", help="username,less than 20 characters")
    _parser.add_argument("password", help="password,less than 20 characters")
    
    arg = _parser.parse_args()
    
    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(arg.debugLevel * 10)

    log.info(f'{arg}')
    
    asyncio.run(main())