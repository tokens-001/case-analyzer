f=open("test.txt","w")
f.write("还是一知半解\n")
f.write("不知道怎么写\n")
f.close()
f=open("test.txt","r")
for line in f:
    print(line)
f.close()


