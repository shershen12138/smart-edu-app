# -*- codeing = utf-8 -*-
import random
import math


def func401(num):
    if num % 2 == 0:
        return "偶数"
    else:
        return "奇数"

def func402(num):
    if 0<=num<=100:
        if num%3==0:
            return True
        else:
            return False
    else:
        return "输入的数不在[0-100]范围内"

def func403(num):
    #几位数
    num=str(num)
    num_digits=len(num)
    #每一位数字
    num_lst = [int(digit) for digit in num]
    #逆序
    reversed_num = num[::-1]
    return num_digits,num_lst, reversed_num


def func404(num1,num2):
    return num1 if num1>num2 else num2

def func405(num1,num2,num3):
    return sorted([num1,num2,num3])

#用户信息表
user_info = [
    ("user1", "password1"),
    ("user2", "password2"),
    ("user3", "password3"),
]

# """生成4位数的随机验证码"""
# def generate_verification_code():
#     return str(random.randint(1000, 9999))

def func406(username, password):
    # verification_code= random.randint(1000, 9999)
    if (username, password) not in user_info:
        return "用户名或密码不正确"
    else:
        return "登录成功"


# '''贪心算法。优先考虑单价便宜的
# 买5送2，相当于75元买7瓶，每瓶10.7元；
# 买3送1，相当于45元买4瓶，每瓶11.25元；
# 单买一瓶 15 元'''


def func407(N):
    per_price=15
    #不参加促销最多能买的瓶数
    n=N//per_price

    total=0
    while(n):
        #先参加促销2 买5瓶送2瓶
        if(n//5>0):
            t1=n//5
            total=total+t1*(5+2)
            n=n-t1*5
        elif(n//3>0):
            #若剩余的不够继续参加促销2，参加促销1 买3瓶送1瓶
            t2=n//3
            total=total+t2*(3+1)
            n=n-t2*3
        elif n<3:
            #不够参加促销
            total=total+n
            n=0
    return total

def func408(deposit):
    if deposit<100000:
        ir=0.015#1.5%
    elif deposit<500000:
        ir=0.02 #2%
    elif deposit<1000000:
        ir=0.03 #3%
    else:
        ir=0.035 #3.5%
    #利息
    interest=deposit*ir
    #1年后本息和
    total=deposit+interest
    return total

def func409(x1,y1,x2,y2,x3,y3):
    a=math.sqrt((x2-x1)**2+(y2-y1)**2)
    b=math.sqrt((x3-x2)**2+(y3-y2)**2)
    c=math.sqrt((x3-x1)**2+(y3-y1)**2)
    #检查是否能构成三角形
    if a+b<=c or a+c<=b or b+c<=a:
        return "不能构成三角形"
    else:
        l=a+b+c
        s=l/2
        area=math.sqrt(s*(s-a)*(s-b)*(s-c))
        return area,l

def func410(x1,y1,x2,y2,x3,y3):
    a=math.sqrt((x2-x1)**2+(y2-y1)**2)
    b=math.sqrt((x3-x2)**2+(y3-y2)**2)
    c=math.sqrt((x3-x1)**2+(y3-y1)**2)
    #检查是否能构成三角形
    if a+b<=c or a+c<=b or b+c<=a:
        return "不能构成三角形"
    else:
        sides_squared = sorted([a ** 2, b ** 2, c ** 2])
        if a==b and b==c:
            return "等边三角形"
        elif math.isclose(sides_squared[0] + sides_squared[1], sides_squared[2]):
            return "直角三角形"
        else:
            return "一般三角形"

def func411(x1,y1,r,x2,y2):
    #计算圆心到点距离
    distance=(x1-x2)**2+(y1-y2)**2
    if distance<=r**2:
        return f"点{(x2,y2)}在圆内"
    else:
        return f"点{(x2,y2)}在圆外"


if __name__ == '__main__':
    pass



