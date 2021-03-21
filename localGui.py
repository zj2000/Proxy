import sys
import os
import traceback
import logging
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *
from PyQt5.QtWidgets import *
from PyQt5.QtWebSockets import *

isStart = False

class Window(QDialog):
    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        
        #self.isStart = False
        #localProxy、remoteProxy的主机地址和端口、用户名和密码
        self.wsPortLayout = QHBoxLayout()
        self.wsPortLabel = QLabel("Websocket Port:")
        self.wsPortLine = QLineEdit("9000")
        self.wsPortLayout.addWidget(self.wsPortLabel)
        self.wsPortLayout.addWidget(self.wsPortLine)
        
        self.localHostLayout = QHBoxLayout()
        self.localHostLabel = QLabel("Local Host:")
        self.localHostLine = QLineEdit("127.0.0.1")
        self.localHostLayout.addWidget(self.localHostLabel)
        self.localHostLayout.addWidget(self.localHostLine)
        
        self.localPortLayout = QHBoxLayout()
        self.localPortLabel = QLabel("Local Port:")
        self.localPortLine = QLineEdit("8888")
        self.localPortLayout.addWidget(self.localPortLabel)
        self.localPortLayout.addWidget(self.localPortLine)
        
        self.remoteHostLayout = QHBoxLayout()
        self.remoteHostLabel = QLabel("Remote Host:")
        self.remoteHostLine = QLineEdit("127.0.0.1")
        self.remoteHostLayout.addWidget(self.remoteHostLabel)
        self.remoteHostLayout.addWidget(self.remoteHostLine)
        
        self.remotePortLayout = QHBoxLayout()
        self.remotePortLabel = QLabel("Remote Port:")
        self.remotePortLine = QLineEdit("8000")
        self.remotePortLayout.addWidget(self.remotePortLabel)
        self.remotePortLayout.addWidget(self.remotePortLine)
        
        self.usrNameLayout = QHBoxLayout()
        self.usrNameLabel = QLabel("User Name:")
        self.usrNameLine = QLineEdit()
        self.usrNameLayout.addWidget(self.usrNameLabel)
        self.usrNameLayout.addWidget(self.usrNameLine)
        
        self.usrPwdLayout = QHBoxLayout()
        self.usrPwdLabel = QLabel("User Password")
        self.usrPwdLine = QLineEdit()
        self.usrPwdLine.setEchoMode(QLineEdit.Password)
        self.usrPwdLayout.addWidget(self.usrPwdLabel)
        self.usrPwdLayout.addWidget(self.usrPwdLine)
        
        totLayout = QVBoxLayout()
        totLayout.addLayout(self.wsPortLayout)
        totLayout.addLayout(self.localHostLayout)
        totLayout.addLayout(self.localPortLayout)
        totLayout.addLayout(self.remoteHostLayout)
        totLayout.addLayout(self.remotePortLayout)
        totLayout.addLayout(self.usrNameLayout)
        totLayout.addLayout(self.usrPwdLayout)
        
        self.startButton = QPushButton('Start')
        self.startButton.clicked.connect(self.OnStartClicked)
        totLayout.addWidget(self.startButton)
        
        self.closeButton = QPushButton('Close')
        self.closeButton.clicked.connect(self.OnCloseClicked)
        totLayout.addWidget(self.closeButton)
        
        self.stateLabel = QLabel("Local Proxy State:")
        self.stateText = QTextBrowser()
        totLayout.addWidget(self.stateLabel)
        totLayout.addWidget(self.stateText)
        self.stateText.setText("CLOSED.")

        self.sendBandwidthLabel = QLabel("Send Bandwidth:")
        self.sendBandwidthText = QTextBrowser()
        totLayout.addWidget(self.sendBandwidthLabel)
        totLayout.addWidget(self.sendBandwidthText)
        
        self.recvBandwidthLabel = QLabel("Recv Bandwidth:")
        self.recvBandwidthText = QTextBrowser()
        totLayout.addWidget(self.recvBandwidthLabel)
        totLayout.addWidget(self.recvBandwidthText)
        
        self.setLayout(totLayout)
        
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.finished.connect(self.websocketDisconnected)
        self.process.started.connect(self.processStarted)
        self.process.readyReadStandardOutput.connect(self.processReadyRead)
    
    
    def OnStartClicked(self):
        global isStart
        if not isStart:
            isStart = True
            self.stateText.setText("STARTED.")
            self.localHost = self.localHostLine.text()
            self.localPort = self.localPortLine.text()
            self.remoteHost = self.remoteHostLine.text()
            self.remotePort = self.remotePortLine.text()
            self.userName = self.usrNameLine.text()
            self.password = self.usrPwdLine.text()
            self.wsPort = self.wsPortLine.text()
            pythonExec = os.path.dirname(os.path.realpath(__file__))+"\\"
            cmdLine = f"python {pythonExec}local.py -wsp {self.wsPort} -lh {self.localHost} -lp {self.localPort} -rh {self.remoteHost} -rp {self.remotePort} {self.userName} {self.password}"
            log.debug(f"{cmdLine}")
            self.process.start(cmdLine)
    
    def OnCloseClicked(self):
        global isStart
        isStart = False
        self.stateText.setText("CLOSED.")
        self.process.kill()
        log.debug("click the close button.")
        
        
    def processReadyRead(self):
        data = self.process.readAll()
        try:
            msg = data.data().decode().strip()
            log.debug(f'msg={msg}')
        except Exception as exc:
            log.error(f'{traceback.format_exc()}')
            exit(1)
        
    def processStarted(self):
        process = self.sender()
        processId = process.processId()
        log.debug(f'pid={processId}')

        self.websocket = QWebSocket()
        self.websocket.connected.connect(self.websocketConnected)
        self.websocket.disconnected.connect(self.websocketDisconnected)
        self.websocket.textMessageReceived.connect(self.websocketMsgRcvd)
        localUrl = f"ws://{self.localHost}:{self.wsPort}/"
        self.websocket.open(QUrl(localUrl))
    
    def websocketConnected(self):
        self.websocket.sendTextMessage('secret')

    def websocketDisconnected(self):
        global isStart
        isStart = False
        self.stateText.setText("CLOSED.")
        self.process.kill()
        log.debug("the process is closed.")

    def websocketMsgRcvd(self, msg):
        log.debug(f'msg={msg}')
        bandwidth = msg.split()
        curTime = QDateTime.currentDateTime().toString('hh:mm:ss')
        self.sendBandwidthText.setText(f"Time{curTime} : {bandwidth[0]}")
        self.recvBandwidthText.setText(f"Time{curTime} : {bandwidth[1]}")

def main():
    app = QApplication(sys.argv)
    app.setStyle("Windows")
    
    w = Window()
    w.move(400,200)
    w.setWindowTitle("LocalGUI")
    w.resize(500,500)
    w.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    
    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)
    
    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)
    
    main()