# -*- coding: utf-8 -*-
# 作业03 列表  学生04
# 错误画像：程序能全部运行，但对题意和条件理解有偏差，
# 属于逻辑错误型（分支条件写反、排序方向搞错）
#（知识点错误：分支条件方向、type 过滤对象、返回码语义、排序键、插入比较方向）

def func301(A,B):
    C = A + B
    return C[7:15]

def func302(A):
    l = len(A)
    if l % 2 == 1:
        return A[l//2]
    else:
        if A[l//2] > A[l//2-1]:
            return A[l//2]
        else:
            return A[l//2-1]

def func303(A):
    if A == A[::-1]:
        return 1
    else:
        return 0

def func304(A):
    for i in range(len(A)-1):
        for j in range(len(A)-1, i, -1):
            if A[i] == A[j]:
                del A[j]
    return A

def func305(A):
    return [i for i in A if type(i) == str]

def isPrime(Num):
    if Num <= 1:
        return False
    for i in range(2, int(Num ** 0.5) + 1):
        if Num % i == 0:
            return False
    return True

def func306(A):
    B = [c for c in A if isPrime(c)]
    B.sort(reverse=True)
    m = 0
    for i in range(len(B)-2):
        flag = 0
        for j in range(i+1, len(B)):
            for k in range(j+1, len(B)):
                if B[i] == B[j] + B[k]:
                    m = m + 1
                    flag = 1
                    break
            if flag == 1:
                break
    return m

def func307(A):
    seed = A[-1]
    sum = seed
    pos = [-1, -1]
    i = -2
    while i >= -len(A):
        if A[i] == seed:
            sum = sum + A[i]
            pos[1] = i
        else:
            if pos[0] == pos[1]:
                pos[0] = pos[1] = i
                seed = sum = A[i]
            else:
                del A[pos[0]:pos[1]-1:-1]
                if pos[0] == -1:
                    A.append(sum)
                else:
                    A.insert(pos[0]+1, sum)
                    pos[0] = pos[0] + 1
                i = pos[0]
                pos[1] = pos[0]
                seed = sum = A[i]
        i = i - 1
    else:
        if pos[0] != pos[1]:
            del A[pos[0]:pos[1]-1:-1]
            if pos[0] == -1:
                A.append(sum)
            else:
                A.insert(pos[0]+1, sum)
    return A

def func308(lst):
    count_ou, count_ji = 0, 0
    for num in lst:
        if num % 2 == 0:
            count_ou += 1
        else:
            count_ji += 1
    if count_ou == count_ji:
        return 1
    elif count_ou > count_ji:
        return 3
    else:
        return 2

def func309(lst):
    lst.sort(key=lambda item: (item[1]+item[2], item[0]), reverse=True)
    max_score = lst[0][1] + lst[0][2]
    lst_result = [[item[0], item[1]+item[2]] for item in lst if item[1]+item[2] == max_score]
    return lst_result

def func310(Num):
    return [i for i in range(2, Num+1) if isPrime(i)]

def func311(A):
    B = []
    for i in range(len(A)):
        C = [int(c) for c in str(A[i])]
        C.reverse()
        B = B + C
    return B

def func312(lst):
    if len(lst) < 2:
        return []
    while len(lst) > 2:
        t1 = [(lst[i] + lst[i+1]) for i in range(len(lst) - 1)]
        mx = max(t1)
        t2 = t1.index(mx)
        lst = lst[:t2] + [(lst[t2] + lst[t2+1]) // 2] + lst[t2+2:]
    return lst

def func313(A):
    B = []
    for col in range(len(A)):
        t = [A[row][col] for row in range(len(A))]
        B.append(t)
    return B

def func314(A):
    A.sort(key=lambda item: (DigAver(item), -item))
    return A

def DigAver(Num):
    lst = [int(c) for c in str(Num)]
    if len(lst) == 0:
        return 0.0
    else:
        return sum(lst)/len(lst)

def func315(A, Num):
    for i in range(len(A)):
        if Num > A[i]:
            A.insert(i, Num)
            break
    else:
        A.append(Num)
    return A

if __name__ == "__main__":
    pass
