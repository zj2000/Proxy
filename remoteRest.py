import asyncio
import aiosqlite
import logging

from sanic import Sanic
from sanic import response
from sanic import exceptions

app = Sanic("RemoteRest")
app.config.dbName = "user.db"

@app.exception(exceptions.NotFound)
async def NotFoundError(req, exc):
    return response.text("not found",status=404)

#查
#查询全部用户信息
@app.get("/user")
async def GetAllUser(req):
    userList = list()
    async with aiosqlite.connect(app.config.dbName) as db:
        sqlQuery = "SELECT username,password,bandwidth FROM users"
        async with db.execute(sqlQuery) as cursor:
            async for row in cursor:
                user = {'username':row[0], 'password':row[1], 'bandwidth':row[2]}
                log.debug(f"{user}")
                userList.append(user)
    return response.json(userList)

#查询某个特定的用户
@app.get("/user/<usrName>")
async def GetOneUser(req, usrName):
    async with aiosqlite.connect(app.config.dbName) as db:
        sqlQuery = f"SELECT username, password,bandwidth FROM users WHERE username = '{usrName}'"
        async with db.execute(sqlQuery) as cursor:
            async for row in cursor:
                user = {'username':row[0], 'password':row[1], 'bandwidth':row[2]}
                log.debug(f"{user}")
                return response.json(user)
    return response.json({},status=404)#没有该用户

#增
@app.post('/user/<info>')
async def AddUser(req,info):
    infoList = info.split(',')
    attrLen = len(infoList)
    if attrLen < 3:
        return response.text("Error: Not enough infomation", status=404)
    
    user = {'username':infoList[0], 'password':infoList[1], 'bandwidth':infoList[2]}
    username = infoList[0]
    password = infoList[1]
    bandwidth = infoList[2]
    if(not username or not password or not bandwidth):
        return response.text("Error: username/password/bandwidth exist null value", status=404)
    async with aiosqlite.connect(app.config.dbName) as db:
        sqlQuery = f"INSERT INTO users VALUES('{username}','{password}',{bandwidth})"
        await db.execute(sqlQuery)
        await db.commit()
    return response.json(user)

#删
@app.delete('/user/<usrName>')
async def DeleteUser(req,usrName):
    async with aiosqlite.connect(app.config.dbName) as db:
        sqlQuery = f"DELETE FROM users WHERE username='{usrName}'"
        await db.execute(sqlQuery)
        await db.commit()
    return response.json({})

#改
@app.put("/user/<info>")
async def UpdateUser(req,info):
    infoList = info.split(',')
    username = infoList[0]
    password = ""
    bandwidth = 0
    sqlQuery = ""
    
    attrLen = len(infoList)
    if attrLen < 2:
        return response.text("Error: Not enough infomation", status=404)
    for i in range(1,attrLen):
        attr = infoList[i].split(':')
        if(attr[0] == "password"):
            password = attr[1]
        elif(attr[0] == "bandwidth"):
            bandwidth = attr[1]
        else:
            return response.text("Error: wrong attribute", status=404)
        
    if(password and bandwidth):#所有属性都要更改
        sqlQuery = f"UPDATE users SET password='{password}',bandwidth={bandwidth} WHERE username='{username}'"
    elif (password and not bandwidth):#只更改密码
        sqlQuery = f"UPDATE users SET password='{password}' WHERE username='{username}'"
    elif (not password and bandwidth):#只更改带宽
        sqlQuery = f"UPDATE users SET bandwidth={bandwidth} WHERE username='{username}'"
    else:
        return response.text("Error: password/bandwidth exist null value", status=404)
    
    async with aiosqlite.connect(app.config.dbName) as db:
        await db.execute(sqlQuery)
        await db.commit()
    return response.json({})

@app.route("/")
async def test(request):
    return response.text("Start to manage your database")

if __name__ == "__main__":
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)
    
    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)
    
    app.run(host="0.0.0.0", port=8000)