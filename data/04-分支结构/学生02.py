# -*- coding: utf-8 -*-
# 作业04 分支结构  学生02
# 错误画像：语法正确但存在运行时错误（NameError / TypeError / AttributeError），
# 部分测试数据会崩溃
#（知识点错误：忘记 str() 转换、变量名写错、函数名拼写错）

# -*- codeing = utf-8 -*-
import random
import math

def func401(num):
    if num % 2 == 0:
        return "偶数"
    else:
        return "奇数"

def func402(num):
    if 0 <= num <= 100:
        if num % 3 == 0:
            return True
        else:
            return False
    else:
        return "输入的数不在[0-100]范围内"

def func403(num):
    num_digits = len(str(num))
    num_lst = [int(digit) for digit in str(num)]
    reversed_num = num[::-1]
    return num_digits, num_lst, reversed_num

def func404(num1, num2):
    return num1 if num1 > num2 else num2

def func405(num1, num2, num3):
    return sorted([num1, num2, num3])

user_info = [
    ("user1", "password1"),
    ("user2", "password2"),
    ("user3", "password3"),
]

def func406(username, password):
    if (username, password) not in userinfo:
        return "用户名或密码不正确"
    else:
        return "登录成功"

def func407(N):
    per_price = 15
    n = N // per_price
    total = 0
    while(n):
        if(n // 5 > 0):
            t1 = n // 5
            total = total + t1 * (5 + 2)
            n = n - t1 * 5
        elif(n // 3 > 0):
            t2 = n // 3
            total = total + t2 * (3 + 1)
            n = n - t2 * 3
        elif n < 3:
            total = total + n
            n = 0
    return total

def func408(deposit):
    if deposit < 100000:
        ir = 0.015
    elif deposit < 500000:
        ir = 0.02
    elif deposit < 1000000:
        ir = 0.03
    else:
        ir = 0.035
    interest = deposit * ir
    total = deposit + interest
    return total

def func409(x1,y1,x2,y2,x3,y3):
    a = math.sqt((x2-x1)**2+(y2-y1)**2)
    b = math.sqt((x3-x2)**2+(y3-y2)**2)
    c = math.sqt((x3-x1)**2+(y3-y1)**2)
    if a+b <= c or a+c <= b or b+c <= a:
        return "不能构成三角形"
    else:
        l = a+b+c
        s = l/2
        area = math.sqrt(s*(s-a)*(s-b)*(s-c))
        return area, l

def func410(x1,y1,x2,y2,x3,y3):
    a = math.sqrt((x2-x1)**2+(y2-y1)**2)
    b = math.sqrt((x3-x2)**2+(y3-y2)**2)
    c = math.sqrt((x3-x1)**2+(y3-y1)**2)
    if a+b <= c or a+c <= b or b+c <= a:
        return "不能构成三角形"
    else:
        sides_squared = sorted([a ** 2, b ** 2, c ** 2])
        if a == b and b == c:
            return "等边三角形"
        elif math.isclose(sides_squared[0] + sides_squared[1], sides_squared[2]):
            return "直角三角形"
        else:
            return "一般三角形"

def func411(x1,y1,r,x2,y2):
    distance = (x1-x2)**2 + (y1-y2)**2
    if distance <= r**2:
        return f"点{(x2,y2)}在圆内"
    else:
        return f"点{(x2,y2)}在圆外"

if __name__ == '__main__':
    pass
