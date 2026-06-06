def 启动():
    print("==任务清单==") #(输出内容)
    print("1.学习python")
    print("2.读书,并记录思考")
    print("3.跟读学习英语")
    print("4.晚上锻炼身体")
    while True: #(只要条件成立，永远循环)
        choice=input("选一个编号:") #(按给出条件赋值);(=是赋值；==是判断)
        if choice=="1": #(如果条件成立输出相应内容)
         print("python学习已经搁置三天了,这应该是首要任务")
        elif choice=="2": #(前面条件不成立时，进行下一个判断)
         print("读书并记录思考同样重要,完善你的赛博日记吧")
        elif choice=="3":
         print("学习英语也是个不错的选择,不过还有更优先的任务")
        elif choice=="4":
         print("这是睡前任务,现在已经要睡觉了吗？")
        elif choice=="5":
         print("今日任务已选择,开工")
         break #(结束循环)
        else: #(其它选项输出)
         print("选项不在清单内,请重新选择")