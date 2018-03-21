import socket
import sys
import time
import math
import traceback
import random
import operator

HOST, PORT = "localhost", 17429
USERNAME, PASSWORD = "Algotraders", "spmuppar"
# HOST, PORT = "localhost", 17429
#USERNAME, PASSWORD = "a", "a"

seen_backup = set()
seen_wm_backup = set()

"""
STATUS
ACCELERATE ANGLE THRUST
BRAKE
BOMB X Y [TIMER=100]
SCAN X Y
SCOREBOARD
CONFIGURATIONS
"""


def distance(pos1, pos2=(0, 0)):
    return math.sqrt(squaredDistance(pos1, pos2))


def squaredDistance(pos1, pos2=(0, 0)):
    return (pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2


def neg(pos):
    return (-pos[0], -pos[1])


def add(pos1, pos2):
    return (pos1[0] + pos2[0], pos1[1] + pos2[1])


def scale(k, pos):
    return (k * pos[0], k * pos[1])


def sub(pos1, pos2):
    return (pos1[0] - pos2[0], pos1[1] - pos2[1])


def dot(pos1, pos2):
    return pos1[0] * pos2[0] + pos1[1] * pos2[1]


def proj(a, b):
    factor = (dot(a, b) / squaredDistance(a))
    return (factor * a[0], factor * a[1])


def perp(a, b):
    return sub(b, proj(a, b))


def angle(pos):
    return math.atan2(pos[1], pos[0])


def norm(vec):
    return scale(1 / distance(vec), vec)


class Player:
    def __init__(self, HOST, PORT, USERNAME, PASSWORD):
        self.stack = set()
        self.seen = seen_backup
        self.seen_wm = seen_wm_backup
        self.notOurs = dict()
        self.data = None

        self.HOST = HOST
        self.PORT = PORT
        self.USERNAME = USERNAME
        self.PASSWORD = PASSWORD

    def __enter__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.HOST, self.PORT))
        self.sock.send((self.USERNAME + ' ' + self.PASSWORD + '\n').encode())
        response = self.sendCommand('CONFIGURATIONS')
        arr = response.split(' ')[1:]
        print(response)
        self.config = dict(zip(arr[0::2], [float(x.strip()) for x in arr[1::2]]))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.sock.close()

    def sendCommand(self, cmd):
        self.sock.send((cmd + '\n').encode())
        return self.sock.recv(4096).decode("utf-8")

    def processData(self, response, isStatus=True):
        try:
            arr = response.split(' ')
            # print(arr)

            processed = dict()
            if isStatus:
                processed["pos"] = (float(arr[1]), float(arr[2]))
                processed["vel"] = (float(arr[3]), float(arr[4]))
            else:
                processed["pos"] = self.data["pos"]
                processed["vel"] = self.data["vel"]
            processed["ourmines"] = list()
            processed["mines"] = list()
            processed["players"] = list()
            processed["bombs"] = list()
            processed["wm"] = list()

            if isStatus:
                counter = 7
            else:
                counter = 3
            nummines = int(arr[counter])
            for i in range(nummines):  # x, y, owner (ONLY IF NOT OURS)
                next = (float(arr[counter + 2 + 3 * i]), float(arr[counter + 3 + 3 * i]), arr[counter + 1 + 3 * i])
                if arr[counter + 1 + 3 * i] != self.USERNAME:
                    processed["mines"].append(next)
                    self.notOurs[next[0:2]] = next[2]
                else:
                    processed["ourmines"].append(next)
                self.seen.add(next[0:2])

            counter += 2 + 3 * nummines
            numplayers = int(arr[counter])
            for i in range(numplayers):  # x, y, dx, dy
                processed["players"].append((float(arr[counter + 1 + 4 * i]), float(arr[counter + 2 + 4 * i]),
                                             float(arr[counter + 3 + 4 * i]), float(arr[counter + 4 + 4 * i])))

            counter += 2 + 4 * numplayers
            numbombs = int(arr[counter])
            for i in range(numbombs):  # x, y
                processed["bombs"].append((float(arr[counter + 1 + 2 * i]), float(arr[counter + 2 + 2 * i])))

            if numbombs != 0:
                counter += 2 + 3*numbombs
                num_wmholes = int(arr[counter])
            else:
                counter += 2 + 2*numbombs
                num_wmholes = int(arr[counter])

            for i in range(num_wmholes):
                next = (float(arr[counter + 1 + 5 * i]), float(arr[counter + 2 + 5 * i]),
                        float(arr[counter + 3 + 5 * i]), float(arr[counter + 4 + 5 * i]), float(arr[counter + 5 + 5 * i]))
                processed["wm"].append(next)
                #print ("worm holes ", next)
                self.seen_wm.add(next[0:5])  #x, y, radius, out_x, out_y

            processed["mines"].sort(key=lambda x: squaredDistance(x, processed["pos"]))
            processed["players"].sort(key=lambda x: squaredDistance(x, processed["pos"]))
            processed["bombs"].sort(key=lambda x: squaredDistance(x, processed["pos"]))

            global seen_backup
            seen_backup = self.seen

            global seen_wm_backup
            seen_wm_backup = self.seen_wm

            return processed
        except:
            return None

    def refreshData(self):
        response = self.sendCommand('STATUS')
        self.data = self.processData(response)
        while self.is_pos_wm(self.data["pos"]):
            self.explore()
            self.refreshData()
            print ("exploring inside WM")

    def setAccel(self, angle, magnitude):
        self.sendCommand("ACCELERATE " + str(angle) + " " + str(magnitude))

    def setBomb(self, pos, delay):
        # requires delay: >=20 in frames where 1 frame = 25milsecond
        self.sendCommand("BOMB " + str(pos[0]) + " " + str(pos[1]) + " " + str(delay))

    def scanXY(self, pos):
        response = self.sendCommand("SCAN " + str(pos[0]) + " " + str(pos[1]))
        if response.find("ERROR") == -1:
            print('scan', len(self.seen))
            res =self.processData(response, False)
            if len(self.data["mines"]) > 0:
                self.waypoint(self.data["mines"][0], self.scanNextMine)
            return res

        else:
            return None

    def is_pos_wm(self, pos, tol=1):
        #proc_data = self.scanXY(pos)
        for wm in self.seen_wm:
            #keyboard()
            # wm[0], wm[1], wm[2] : x, y, radius of wm
            dist = distance(pos, [wm[0], wm[1]])  #find distance between (x, y) and (wm_x, wm_y)
            if dist <= wm[2]:
                #print("MINE (", pos, " IS WITHIN THE RANGE OF WM")
                return True
        return False

    def isOurMine(self, minepos):
        for mine in self.data["ourmines"]:
            if minepos[0] == mine[0] and minepos[1] == mine[1]:
                return True
        return False

    def shortestVectorTo(self, target):
        offsets = [(self.config["MAPWIDTH"], 0), (0, self.config["MAPHEIGHT"]),
                   (self.config["MAPWIDTH"], self.config["MAPHEIGHT"])]

        vec = sub(target, self.data["pos"])
        minLen = squaredDistance(vec)
        minVec = vec

        for offset in offsets:
            vec = sub(target, sub(self.data["pos"], offset))
            if squaredDistance(vec) < minLen:
                minLen = squaredDistance(vec)
                minVec = vec
            vec = sub(target, sub(self.data["pos"], neg(offset)))
            if squaredDistance(vec) < minLen:
                minLen = squaredDistance(vec)
                minVec = vec

        return minVec

    def waypoint(self, target, callback=None):  # fly through this point exactly. blocks until done.
        vecTo = self.shortestVectorTo(target)
        self.seen.add(target[0:2])
        print("Waypointing to ", target, " which is at angle ", angle(vecTo), " from me")
        while distance(vecTo) > self.config["CAPTURERADIUS"] and not self.isOurMine(target) and not self.is_pos_wm(target):
            self.refreshData()
            # if len(p.seen) < 10:
            #  if len(self.data["mines"]) > 0:
            #    for mine in self.data["mines"]:
            #      if (not self.isOurMine(mine)) and (distance(self.data["pos"], target) > 1.5 * distance(self.data["pos"], mine)):
            #        self.stack.add(target)
            #        target = mine
            vecTo = self.shortestVectorTo(target)
            vel = self.data["vel"]
            self.setAccel(angle(add(neg(perp(vecTo, vel)), scale(1 / distance(vecTo), vecTo))), 1)
            if(distance(vecTo)>100):
                print ("Threw a bomb",self.data['pos'])
                self.setBomb(self.data['pos'],10)

            # if len(p.seen) >= 10:
            for mine in self.notOurs.keys():
                if distance(self.shortestVectorTo(mine)) * 1.5 < distance(
                        vecTo):  # if it's more than 1.5 times further than a nearer one, cancel.
                    print("canceling waypoint")
                    return
            if callback is not None:
                callback()
        self.notOurs.pop(target[0:2], None)
        # if len(p.seen) < 10:
        #  for targ in self.stack:
        #    self.waypoint(targ, self.scanNextMine)
        #    self.stack.discard(targ)

    def scanRandom(self):
        # self.exploringIndex
        # scanResults =
        # if scanResults != None:
        #  add everything in scanResults["mines"] to self.seen

        self.scanXY((random.random() * self.config["MAPWIDTH"], random.random() * self.config[
            "MAPHEIGHT"]))  # add(scale(300, norm(self.data["vel"])), self.data["pos"])

        # if scanResults != None and len(scanResults["mines"]) > 0:
        #  self.waypoint(scanResults["mines"][0])

    def explore(self):
        vel = self.data["vel"]

        if (distance(vel) == 0):
            self.setAccel(random.random(), 1)
        else:
            self.setAccel(angle(vel), 1)

            bombdisp = scale((self.config["BOMBPLACERADIUS"]) / math.sqrt(squaredDistance(vel)), vel)
            if random.random()<0.3 and len(self.data["mines"]) == 0:
                self.setBomb(self.data["pos"], 0)
            #if len(self.data["mines"]) == 0:
                #self.setBomb(add(self.data["pos"], bombdisp), 30)

            self.scanRandom()

    def scanNextMine(self):
        if random.random() < len(self.seen) /(len(self.seen) *2):
            m = random.choice(tuple(self.seen))
            while 1000 / distance(m, self.data["pos"]) < random.random():  # scanning needs to be weighted to be more likely for more nearby
                m = random.choice(tuple(self.seen))
            self.scanXY(m)
        else:
            self.scanRandom()

    def inTopScore(self, name):
        response = self.sendCommand("SCOREBOARD")
        arr = response.split(' ')
        n = len(arr)//3
        p={}
        for i in range(n):
            p[arr[i*3]]=arr[i*3+1]
        newP = dict(sorted(p.items(), key=operator.itemgetter(1), reverse=True)[:3])
        if name in newP:
            return True
        return False

    def waypointToNearest(self):
        if len(self.notOurs) > 0:
            target = min(self.notOurs.keys(), key=lambda mine: squaredDistance(mine, self.data["pos"]) * (
            0.1 if self.inTopScore(self.notOurs[mine]) else 1))
            if distance(target, self.data["pos"]) > 1500:
                diff = sub(target, self.data["pos"])
                bombdisp = scale((self.config["BOMBPLACERADIUS"]) / math.sqrt(squaredDistance(diff)), diff)
                if len(self.data["mines"]) == 0:
                    self.setBomb(add(self.data["pos"], bombdisp), 30)
            self.waypoint(target, self.scanNextMine)
        else:
            if(random.random() < 0.5):
                self.scanNextMine()
            else:
                if(random.random()<0.5):
                    self.refreshData()
                else:
                    self.explore()


while True:
    try:
        with Player(HOST, PORT, USERNAME, PASSWORD) as p:
            p.setAccel(0.3, 1)
            time.sleep(1)
            while len(p.seen) < 4:
                p.refreshData()
                print(p.data)
                # print(math.sqrt(squaredDistance(p.data["vel"])))
                if len(p.data["mines"]) >0:
                    p.waypoint(p.data["mines"][0], p.scanNextMine)
                    # for index, mine in enumerate(p.data["mines"]):
                    #  if index < (len(p.data["mines"]) - 1):
                    #    p.toVisit.add(mine)
                    #  else:
                    #    p.waypoint(mine)
                    # for mine in p.toVisit:
                    #  p.waypoint(mine)
                    # p.toVisit = set()
                else:
                    p.explore()
            while True:
                p.waypointToNearest()
    except Exception as e:
        print("Error", str(e))
        traceback.print_exc()

        # ('Error', "invalid literal for float(): -13.08585358'")
        # ('Error', "could not convert string to float: '")
        # ('Error', "invalid literal for int() with base 10: '1.8850081045206708E-125'"
        # ('Error', 'could not convert string to float: Unable')
        # ('Error', "invalid literal for int() with base 10: '2940.086815219818'")
        # ('Error', 'could not convert string to float: Unable')
        # ('Error', 'could not convert string to float: Unable')