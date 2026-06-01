scores=[]
body=input("身体状态(1-10):")
mood=input("情绪状态(1-10):")
energy=input("精力状态(1-10):")
scores.append(body)
scores.append(mood)
scores.append(energy)
print("今日记录:"+str(scores))
f=open("/Users/jingzhe/奇点/energy_log.txt","a")
f.write(str(scores)+"\n")
f.close()
all_entries=[]
f=open("/Users/jingzhe/奇点/energy_log.txt","r")
for line in f:
    all_entries.append(line)
f.close()
print(all_entries)