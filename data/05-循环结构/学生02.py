# -*- coding: utf-8 -*-
# 作业05 循环结构  学生02
# 错误画像：语法正确但存在运行时错误（死循环 / NameError / AttributeError），
# 部分测试数据会崩溃或卡死
#（知识点错误：/= 产生小数导致死循环、字典键名漏引号、函数名拼写错）

def func501(num):
    ret = ""
    while num != 0:
        ret = str(num % 2) + ret
        num /= 2
    return ret

def func502(num):
    temp = int(num, 16)
    ret = ""
    while temp != 0:
        ret = str(temp % 2) + ret
        temp //= 2
    return ret

def func503(ch):
    if ch.isupper():
        ch = ch.lower()
    elif ch.islower():
        ch = ch.upper()
    return ch

def func504(s):
    ret1, ret2 = 0, 0
    for i in s:
        if ord('0') == ord(i):
            ret1 += 1
        else:
            ret2 += 1
    return [ret1, ret2]

def func505(n):
    ret = 0
    for i in range(1, n+1):
        for j in range(1, n+1):
            res = n - 15*i - 3*j
            if res <= 0:
                break
            if res % 2 == 0:
                ret += 1
    return ret

def func506(lst):
    ret1, ret2, ret3 = 0, 0, 0
    for i in lst:
        if i >= 90:
            ret1 += 1
        elif 60 <= i and i <= 89:
            ret2 += 1
        elif i < 60:
            ret3 += 1
    return [ret1, ret2, ret3]

def func507(lst):
    ret = {'name': '', 'age': 0}
    for i in lst:
        if i[age] > ret['age']:
            ret['name'] = i['name']
            ret['age'] = i[age]
    return ret

def func508(n):
    x, ret = 2, 0
    if n <= 20:
        ret = n/2
    elif n <= 10*2+10*2*0.95:
        ret = 10+(n-20)/(2*0.95)
    elif n <= 10 * 2 + 10 * 2 * 0.95 + 30*2*0.8:
        ret = 20 + (n - 10*2 - 10*2*0.95) / (2 * 0.8)
    else:
        ret = 50 + (n - 10 * 2 - 10 * 2 * 0.95 - 30*2*0.8) / (2 * 0.5)
    return int(ret)

def func509(n, dis):
    import math
    l, nowdis = len(dis), 0
    cur_ret = 0
    for cur_start in range(l):
        cur_end = cur_start
        while cur_end < l:
            nowdis = sum(dis[cur_start:cur_end+1])
            if nowdis <= 5:
                nowcost = 2
            else:
                nowcost = 2 + math.ciel((nowdis-5)/5)
            if n >= nowcost:
                if cur_end + 1 == l:
                    if cur_ret < cur_end - cur_start:
                        cur_ret = cur_end - cur_start + 1
                    break
                else:
                    cur_end += 1
            else:
                if cur_ret < cur_end - cur_start:
                    cur_ret = cur_end - cur_start
                break
    return cur_ret

def func510(n):
    List = []
    for i in range(2, n):
        flag = 0
        for j in range(2, i):
            if j*j > i:
                break
            if i % j == 0:
                flag = 1
                break
        if flag == 0:
            List.append(i)
    List.sort()
    return List

def func511(n, h):
    meter, height = 0, h
    meter = height
    height /= 2
    for i in range(1, n):
        meter += height*2
        height /= 2
    return [meter, height]

def func512(n):
    return n == sum([int(item)**4 for item in str(n)])

def func513(n):
    result = 0
    for i in range(10, n+1):
        count = 0
        for j in range(1, i+1):
            if i % j == 0:
                count += 1
        if count == 4:
            result += i
    return result

def func514(lst):
    total = 0
    step = 0
    for i in lst:
        if i == 1:
            step = 1
        elif i == 2:
            if step == 0 or step == 1:
                step = 2
            else:
                step += 2
        else:
            break
        total += step
    return total

def func515(m, step, n):
    distance = 0
    for i in range(n):
        distance += step
        if distance > m:
            break
        elif distance == m:
            return i+1
        else:
            distance -= step//2
    return False

if __name__ == "__main__":
    pass
