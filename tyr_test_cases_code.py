#sex:F age:39 cho:105 smo:N hdl:60 sbp:100 med:N out:<1
chol = [[[0,0,0,0,0],[4,3,2,1,0],[7,5,3,1,0],[9,6,4,2,1],[11,8,5,3,1]], # male
        [[0,0,0,0,0],[4,3,2,1,1],[8,6,4,2,1],[11,8,5,3,2],[13,10,7,4,2]]] # female
ages = [[-9,-4,0,3,6,8,10,11,12,13],[-7,-3,0,3,6,8,10,12,14,16]]
smoke = [[8,5,3,1,1],[9,7,4,2,1]]
hdls = [-1,0,1,2] # same points for both m/f
sysBP = [[[0,0,1,1,2], # untreated m
          [0,1,2,2,3]], # treated m
         [[0,1,2,3,4], # untreated f
          [0,3,4,5,6]]] # treated f
pointList = [[1,1,1,1,1,2,2,3,4,5,6,8,10,12,16,20,25],[1,1,1,1,2,2,3,4,5,6,8,11,14,17,22,27]]

def testCases(sex,age,cho,smo,hdl,sbp,med):
    gender = int(sex == "F") # 0 if M, 1 if F
    smokeStat = smo == "Y" # True if Y, False if N
    medStat = int(med == "Y") # 0 if N, 1 if Y
    points = 0

    if age <= 39:
        ageIndex = 0
    elif age >= 70:
        ageIndex = 4
    else :
        for h in range(3) :
            if age >= (40 + 10 * h) and age < (40 + 10 * (h + 1)) :
                ageIndex = h + 1
    if age <= 34 :
        points += ages[gender][0]
    else:
        for i in range(len(ages[gender])):
            if age >= (35 + 5 * i) and age < (35 + 5 * (i + 1)) :
                #print("age",ages[gender][i - 2])
                points += ages[gender][i + 1]
    #print(points)
    if cho >= 280:
        points += chol[gender][4][ageIndex]
    elif cho >= 160 and cho < 280:
        for j in range(len(chol[gender]) - 2):
            if cho >= (160 + 40 * j) and cho < (160 + 40 * (j + 1)):
                #print("cho",chol[gender][j + 1][ageIndex])
                points += chol[gender][j + 1][ageIndex]
    #print(points)
    if smokeStat :
        points += smoke[gender][ageIndex]
    #print(points)
    if hdl >= 60:
        points += hdls[0]
    elif hdl < 40:
        points += hdls[3]
    elif hdl >= 40 and hdl <= 49 :
        points += hdls[2]
    #print(points)
    if sbp >= 160 :
        points += sysBP[gender][medStat][4]
    elif sbp >= 120 and sbp < 130:
        points += sysBP[gender][medStat][1]
    elif sbp >= 130 and sbp < 140:
        points += sysBP[gender][medStat][2]
    elif sbp >= 140 and sbp < 160:
        points += sysBP[gender][medStat][3]
    #print(points)
    risk = ""
    if gender == 0 :
        if points < 0:
            risk += "<1"
        elif points >= 17:
            risk += ">30"
        else :
            risk += str(pointList[gender][points])
    else: 
        if points < 9: 
            risk += "<1"
        elif points >= 25:
            risk += ">30"
        else :
            risk += str(pointList[gender][points - 9])
    print(f"sex:{sex} age:{age} cho:{cho} smo:{smo} hdl:{hdl} sbp:{sbp} med:{med} out:{risk}")

genderCase = ["M","F"]
smokeCase = ["Y","N"]
""""
for i in range(20,80,4):
    for j in range(39,61,10):
        for k in range(2):
           for l in range(2):
               for m in range(119,161,9):
                    for n in range(2):
                        for o in range(159,281,40):
                            testCases(genderCase[k],i,o,smokeCase[l],j,m,smokeCase[n])

#def testCases(sex,age,cho,smo,hdl,sbp,med):
testCases("M",41,100,"N",51,121,"N") #out:1
testCases("F",39,105,"N",60,100,"N") #out:<1
testCases("M",72,300,"Y",30,170,"Y") #out:>30
testCases("F",79,100,"N",100,100,"N") #out:3
"""
count = 0
for i in range(20,80,9):
    for j in range(2):
        for l in range(119,161,18):
             for o in range(159,281,40):
                for k in range(2):
                    for p in range(2):
                        for r in range(39,61,10):
                            count += 1
                            if count % 3 == 0:
                                testCases(genderCase[k],i,o,smokeCase[p],r,l,smokeCase[j])