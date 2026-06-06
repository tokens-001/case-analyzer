import starter
import energy
import case_analyzer

while True:
      print("\n== 奇点工具箱 ==")
      print("1. 每日任务启动器")
      print("2. 能量日记")
      print("3. 判例拆解助手")
      print("0. 退出")
      choice = input("选一个功能：")
      if choice == "1":
          starter.启动()
      elif choice == "2":
          energy.启动()
      elif choice == "3":
          case_analyzer.启动()
      elif choice == "0":
          print("再见！")
          break
      else:
          print("选项不存在，重新选")