from robodk.robolink import *
from robodk.robomath import *

# Connect to RoboDK
RDK = Robolink()


# Find robot
robot = RDK.Item('UR5', ITEM_TYPE_ROBOT)

if not robot.Valid():
    raise Exception("UR5 robot not found in RoboDK")


# Set speed
# MoveL hastighed
robot.setSpeed(300)          # mm/s

# MoveJ hastighed
robot.setSpeedJoints(300)    # grader/s

# Acceleration
robot.setAcceleration(750)

plate_frame = RDK.AddFrame('Plate_Frame')
plate_frame.setPose(rotz(pi/4))   # prøv -45 grader først

robot.setPoseFrame(plate_frame)

# Start position
robot.MoveJ([90, -90, 90, 90, 90, 0])



#Hvor er modulet i batteriet:
Højde__Modul_batteri = 8  # Dette er vigtigt, ellers kører den for langt ned, eller er for højt oppe, når den skal gribe modulet. Det er en variabel, som kan justeres efter behov.

Højde_For_Lid_Batteri = 21 # Dette er højde hvor Lid er på batteriet
Højde_For_Lid_Bord = 23     #Dettee er højde på bordet

Højde_For_Modul_Bord = 30 # Dette er højden for modulet på bordet

Sikkerheds_Z = 100  # Dette er en sikkerheds højde, det er hvor højt vi vil kører over til de næste targets


#Vælg modul:
# K = [3,4,5,6] # Her skal de moduler der skal skifte komme ind, det kommer fra inputs fra kammeraet.
J = 0       #Dette er en variabel det bliver styret. Den fortælle hvor langt vi er i arrayet.



#Dette under er udregning af hvor modulet er i batteriet, og dermed hvor robotten skal køre hen for at hente det, og aflevere det. Det er vigtigt at den bliver defineret på denne måde, da det er den måde den bliver brugt i koden, og det er også den måde den bliver opdateret på, når vi kommer længere ned i koden.
def Udregning_af_Modul(Modul):
    if Modul > 4:    #Her kigger den på om muodulet er større end 4

        offsetx=71.5      
        offsety=47    
        kol1 = offsetx  

        
        if Modul == 5:  #modul er jo på samme sted som 4 i kolonne 1, så den skal have samme offset i x-retning.
                i = 4
        #De andre bliver regnet på samme som det ovenover.
        elif Modul == 6:
                i = 3
        elif Modul == 7:
                i = 2
        elif Modul == 8:
                i = 1
            
        kol2 = offsety*i

    #Hvis det ikke er større end 4
    else:
        offsety=47
        kol1 = 0
        kol2 = offsety*Modul
        





    target_1 = transl(-213-kol1, -207-kol2, Sikkerheds_Z) * rotx(pi) * rotz(-pi/2) #Her bliver target_1 defineret, det er den position robotten skal køre hen til for at være over modulet,
    target_2 = transl(-213-kol1, -207-kol2, Højde__Modul_batteri) * rotx(pi) * rotz(-pi/2) #Her bliver target_2 defineret, det er den position robotten skal køre hen til for at være ved modulet, og dermed kunne gribe det. 

    return target_1, target_2 #Her bliver target_1 og target_2 returneret, så de kan bruges i resten af koden.


#Placering af moduler (Hvor de dårlige moduler skal afleveres):
target4 = transl(-400, -325, Sikkerheds_Z) * rotx(pi) * rotz(-pi/2)  
target5 = transl(-400, -325, Højde_For_Modul_Bord) * rotx(pi) * rotz(-pi/2)


#Afhentning af gode moduler:
target6 = transl(-67, -289, 90) * rotx(pi) * rotz(-pi/2) * roty(-pi/4)



#Opsamling af låg:
target11 = transl(-246.7, -324, Sikkerheds_Z) * rotx(pi)
target12 = transl(-246.7, -324, Højde_For_Lid_Batteri) * rotx(pi)

#Placing af låg:
target13 = transl(-261.7, -49, Sikkerheds_Z) * rotx(pi)
target14 = transl(-261.7, -49, Højde_For_Lid_Bord) * rotx(pi)



def Læs_Moduler_Fra_DI():
    K = []

    for di in range(8):
        value = robot.getDI(di)
        value = float(value)

        print("DI", di, "=", value)

        if value == 1.0:
            Modul = di + 1
            K.append(Modul)

    print("K =", K)
    return K


def Pick_lid(above, down):

    #Griberne skal åbne

    Open_Griber()

    robot.MoveJ(above) 
    robot.MoveL(down)
    
     #GRIBER SKAL LUKKE

    Close_Griber()
 

    robot.MoveL(above)

def Place_lid(above, down):
    
    robot.MoveJ(above)
    robot.MoveL(down)

    Open_Griber()

    
    robot.MoveL(above)



def Modul_placering(Modul,Stil): #kører hen til det modul, som vi ønsker at kører hen til. 

    target1, target2 = Udregning_af_Modul(Modul) #Her bliver target_1 og target_2 defineret, ved at køre funktionen Udregning_af_Modul, som tager modulet som input, og returnerer target_1 og target_2, som er de positioner robotten skal køre hen til for at hente modulet.
    
    
    robot.MoveJ(target1) #Her kører robotten hen til target_1, som er den position robotten skal køre hen til for at være over modulet, og dermed kunne gribe det.
    robot.MoveL(target2) #Her kører robotten hen til target_2, som er den position robotten skal køre hen til for at være ved modulet, og dermed kunne gribe det.
    if Stil == 0:
        Close_Griber()
    else :
        Open_Griber()
    
    robot.MoveL(target1) #Her kører robotten op igen, efter at have gribet modulet, så den er klar til at køre hen til det næste target.
    
def Aflevere_Moduler():
    robot.MoveJ(target4) #Her kører robotten hen til target_4, som er den position robotten skal køre hen til for at være over det sted hvor de dårlige moduler skal afleveres, og dermed kunne aflevere det.
    robot.MoveL(target5) #Her kører den ned, så den bliver placret pænt.

    Open_Griber()

    robot.MoveJ(target4) #Her kører robotten op igen, efter at have afleveret modulet, så den er klar til at køre hen til det næste target.

def Afhentning_Af_Gode_Moduler():
    robot.MoveJ(target6)    #Kører hen til target_6, som er den position robotten skal køre hen til for at være over det sted hvor de gode moduler skal afhentes, og dermed kunne hente det.

    pose = robot.Pose() #Gemmer positionen af koordinat systemet
    Down_pose = pose * transl(0, 0, 97) #ligger det gemte koordinat system til en translation langs det.
    robot.MoveL(Down_pose)

    Close_Griber()

    Up_pose = pose * transl(0, 0, 0) # kunne også bare være pose, fordi det er en translation der kører tilbage.
    robot.MoveL(Up_pose)





def Open_Griber():
    robot.setDO(5, 0)
    robot.setDO(4, 1)
    pause(0.5)

def Close_Griber():
    robot.setDO(4, 0)
    robot.setDO(5, 1)
    pause(0.5)
    
    


#Dette under er hoved programmet:

# Pick up lid pos (Battery):
Pick_lid(target11, target12)    #Lid skal fjernes først.

#Place lid pos (Battery):
Place_lid(target13, target14)   # Så skal den placeres lid.


#Her skal der være en måde hvor den læser inputs:

robot.setDO(0, 1) #dette giver besked til vision

pause(0.5)

Læs_Moduler_Fra_DI()

K = Læs_Moduler_Fra_DI() # Denne skal bruges senere, når vi får inputs

robot.setDO(0, 0) #dette slukker beskeden til vision.


#Kode for dårlige emner:
for i in range(1, len(K)+1):    #Her kører den så mange gange som der er moduler i arrayet K, som er det array der indeholder de moduler der skal skiftes.
    Modul = K[J]    #Her bliver modulet defineret, ved at kigge i arrayet K, og tage det modul der er på position J, som starter på 0, og dermed bliver det første modul i arrayet K, som er det modul der skal skiftes.
    J += 1          #Her bliver J opdateret, så den næste gang den kører, så kigger den på det næste modul i arrayet K, og dermed bliver det næste modul der skal skiftes.
    Modul_placering(Modul,0)  #Her kører den hen til det modul, som vi ønsker at kører hen til, og dermed hente det, og aflevere det.
    Aflevere_Moduler()  #Her kører den hen til det sted hvor de dårlige moduler skal afleveres, og dermed kunne aflevere det.

#Kode for afhentning af gode emner:
J=0     #Bliver nødt til at starte J på 0 igen, da den skal kigge på det første modul i arrayet K, som er det første modul der skal afhentes.

for i in range(1, len(K)+1):    #Her kører den så mange gange som der er blevet fjernet moduler, som er det samme som længden af arrayet K, som er det array der indeholder de moduler der skal skiftes, og dermed afhentes.
    Afhentning_Af_Gode_Moduler()    #Her kører den hen til det sted hvor de gode moduler skal afhentes, og dermed kunne hente det.
    Modul = K[J]    #Her bliver modulet defineret, ved at kigge i arrayet K, og tage det modul der er på position J, som starter på 0, og dermed bliver det første modul i arrayet K, som er det modul der skal placeres.
    
    Modul_placering(Modul,1)  #Her kører den hen til det modul, som vi ønsker at kører hen til, og dermed hente det, og aflevere det.
    J += 1                  #Her bliver J opdateret, så den næste gang den kører, så kigger den på det næste modul i arrayet K, og dermed bliver det næste modul der skal placeres.

#Hent lid fra placring pos:
Pick_lid(target13, target14)    #Her skal det være griberne der samler låget op igen, hvor vi placerede det.

#Place lid på battery:
Place_lid(target11, target12)   #Her skal det være griberne der placerer låget på batteriet igen, hvor vi fjernede det fra i starten.

# Slut position
robot.MoveJ([90, -90, 90, 90, 90, 0])



print("Test movement finished")


