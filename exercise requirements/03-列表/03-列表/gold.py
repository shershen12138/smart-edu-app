import math

def func301(A,B):
    C = A + B
    return C[7:15]

def func302(A):
    l=len(A)
    if l % 2 == 1:
        return A[l//2]
    else:
        if A[l//2]<A[l//2-1]:
            return A[l//2]
        else:
            return A[l//2-1]

def func303(A):
    if A==A[::-1]:
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
    return [i for i in A if type(i)==int]

def isPrime(Num):
    if Num <= 1:
        return False
    for i in range(2, int(Num ** 0.5) + 1):
        if Num % i == 0:
            return False
    return True

def func306(A):
    B=[c for c in A if isPrime(c)==True]
    B.sort(reverse=True)
    m=0
    for i in range(len(B)-2):
        flag=0
        for j in range(i+1,len(B)):
            for k in range(j+1,len(B)):
                if B[i] == B[j]+B[k]:
                    m=m+1
                    flag=1
                    break
            if flag == 1:
                break
    return m

def func307(A):
    seed=A[-1]
    sum=seed    
    pos=[-1,-1]
    i = -2
    while i>=-len(A):
        if A[i]==seed:
            sum=sum+A[i]
            pos[1]=i
        else:
            if pos[0]==pos[1]:
                pos[0]=pos[1]=i
                seed=sum=A[i]
            else:
                del A[pos[0]:pos[1]-1:-1]
                if pos[0]==-1:
                    A.append(sum)
                else:
                    A.insert(pos[0]+1,sum)
                    pos[0]=pos[0]+1                    
                i=pos[0]
                pos[1]=pos[0]
                seed=sum=A[i]
        i=i-1
    else:
        if pos[0]!=pos[1]:
            del A[pos[0]:pos[1]-1:-1]
            if pos[0]==-1:
                A.append(sum)
            else:
                A.insert(pos[0]+1,sum)
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
        return 2
    else:
        return 3

def func309(lst):
    lst.sort(key=lambda item: (item[1]+item[2], -item[0]), reverse=True)
    max_score = lst[0][1] + lst[0][2]
    lst_result = [[item[0], item[1]+item[2]] for item in lst if item[1] + item[2] == max_score]
    return lst_result

def func310(Num):
    return [i for i in range(2,Num+1) if isPrime(i)==True]
   
def func311(A):
    B=[]
    for i in range(len(A)):
        C=[int(c) for c in str(A[i])]
        C.reverse()
        B=B+C
        #B=B+list(reversed([int(c) for c in str(A[i])]))
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
    B=[]
    for col in range(len(A)):
        t=[A[row][col] for row in range(len(A))]
        B.append(t)
    return B    

def DigAver(Num):
    lst=[int(c) for c in str(Num)]
    if len(lst)==0:
        return 0.0
    else:
        return sum(lst)/len(lst)

def func314(A):
    A.sort(key=lambda item: (DigAver(item), -item))
    return A

def func315(A,Num):
    for i in range(len(A)):
        if Num<A[i]:
            A.insert(i,Num)
            break
    else:
        A.append(Num)
    return A

if __name__=="__main__":
    pass

    '''
    print("=======func301======")    
    print(func301([1,2,3,4,5,6,7,8,9,10],[100,101,102,103,104,105,106,107,108,109,110]))
    print(func301([1,2,3,4,5,6,7,8,9,10,11,12],[100,101,102,103,104,105,106,107,108,109,110]))
    print(func301([1,2,3,4,5,6,7,8,9,10,11,12,13],[100,101,102,103,104,105,106,107,108,109,110]))
    print(func301([1,1,1,1,1,1,1,2,2,2],[3,3,4,5,6,7,8,9,10,11,12]))
    print(func301([1],[100,101,102,103,104,105,106]))
    print(func301([],[]))
    print(func301([1],[100]))
    print(func301([1,2,3,4,5,6,7,8],[]))
    print(func301([1,2,3,4,5,6,7],[100]))
    print(func301([1,2,3,4,5,6,7],[]))    
    

    print("=======func302======")
    print(func302([1]))
    print(func302([1,2]))
    print(func302([1,2,3]))
    print(func302([1,3,2,4]))
    print(func302([1,3,3,4]))
    print(func302([1,2,3,4]))
    print(func302([1,2,3,4,5]))
    print(func302([1,2,3,4,5,6]))
    print(func302([1,2,4,3,5,6]))
    print(func302([1,1,1,1,1,1]))    

    print("=======func303======")
    print(func303([1,1,1,1,1,1]))
    print(func303([1,1,2,1,1]))
    print(func303([1,2,2,2,1]))
    print(func303([1]))
    print(func303([1,1,2]))
    print(func303([1,0,1]))
    print(func303([1,2,3,4,5,6,1,1,6,5,4,3,2,1]))
    print(func303([0,1]))
    print(func303([0,0,0,0]))
    print(func303([0]))

    print("=======func304======")
    print(func304([0,0,0]))  
    print(func304([0]))
    print(func304([0,0,0,1,1,1,1]))
    print(func304([0,0,1,2,3,4,5,6,7,7]))
    print(func304([1,1,1,1,1,1,1,1,1,1,1,1,1]))
    print(func304([1,1,1,1,1,1,1,1,1,1,1,1,0]))
    print(func304([1,1,2,2,3,3,1]))
    print(func304([1,1,4,2,3,3,1]))
    print(func304([1,1,2,2]))
    print(func304([3]))

    print("=======func305======")
    print(func305([2356,"0","1",1234]))
    print(func305(["2356"]))
    print(func305([0]))
    print(func305(["1",'2356',0.0,1.0,"1234"]))
    print(func305([111,2356,0,1,1234]))
    print(func305([1234.0]))
    print(func305([[2222],2356,0,1,1234]))
    print(func305([[12,12,2356,0,1,1234]]))
    print(func305(["222",2356,[0,1,1234]]))
    print(func305(['9090',"2356,0,1",1234]))
    print(func305([10,2356,0,1,1234]))
'''

    # print("=======func306======")    
    # print(func306([2,3,5,1,4,10]))
    # print(func306([7,4,10,2,5,1,0,-1]))
    # print(func306([1,9,2,4,13,15,61]))
    # print(func306([1,1,1,1,1]))
    # print(func306([2,3]))
    # print(func306([59,7,2,61,61,2]))
    # print(func306([3,7,10,2]))
    # print(func306([2,2]))
    # print(func306([2]))
    # print(func306([2,3,5,7]))

'''
    print("=======func307======")
    print(func307([35,1,1,1,1,1,99,2,2,2,2,46]))
    print(func307([35,1,1,1,1,1,99,2,2,2,2,8]))
    print(func307([35,1,1,1,1,1,99,2,2,2,2,2]))
    print(func307([1,1,1,1,1,1,99,2,2,2,2,2]))
    print(func307([1]))
    print(func307([1,1,1,1,1,1,99,2,2,2,3,2]))
    print(func307([1,1,1,1,1,1,1,2,2,2,2,2]))
    print(func307([1,1,1,1,1,1]))
    print(func307([2,1,1,1,1,1]))
    print(func307([1,2]))

    print("=======func308======")
    print(func308([1]))
    print(func308([2]))
    print(func308([1, 2]))
    print(func308([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
    print(func308([99999, 88888, 77777, 66666, 55555, 44444]))
    print(func308([111, 333, 555, 777, 999]))
    print(func308([222, 444, 666, 888]))
    print(func308([666, 7777, 888, 9999, 555, 444, 333]))
    print(func308([10, 10, 10, 9, 9]))
    print(func308([100, 65, 120, 63, 130, 61, 140]))

    print("=======func309======")
    print(func309([[202301, 70, 90], [202302, 90, 70], [202203, 85, 85]]))
    print(func309([[202203, 100, 60], [202202, 90, 85], [202201, 60, 100]]))
    print(func309([[202206, 90, 80], [202205, 80, 90]]))
    print(func309([[202101, 70, 70], [202102, 95, 90], [202103, 80, 80], [202010, 95, 90], [202104, 85, 88]]))
    print(func309([[201901, 80, 90], [201902, 90, 95], [201903, 80, 85], [201904, 100, 85]]))
    print(func309([[201904, 60, 60], [201903, 70, 50], [201902, 40, 80], [201901, 30, 90]]))
    print(func309([[202101, 70, 70], [202102, 95, 90], [202103, 80, 80], [202010, 95, 90], [202104, 85, 88], [202105, 90, 100]]))
    print(func309([[201801, 70, 75], [201802, 80, 100], [201803, 100, 80], [201810, 96, 96], [201804, 85, 88], [201805, 94, 98]]))
    print(func309([[202101, 80, 90], [202001, 90, 90], [201901, 90, 90]]))
    print(func309([[201522, 50, 50]]))    

    print("=======func310======")
    print(func310(10))
    print(func310(1))
    print(func310(2))
    print(func310(20))
    print(func310(30))
    print(func310(40))
    print(func310(50))
    print(func310(60))
    print(func310(70))
    print(func310(100))

    print("=======func311======")
    print(func311([2356,0,1,1234]))
    print(func311([2356]))
    print(func311([0]))
    print(func311([1,2356,0,1,1234]))
    print(func311([111,2356,0,1,1234]))
    print(func311([1234]))
    print(func311([2222,2356,0,1,1234]))
    print(func311([12,12,2356,0,1,1234]))
    print(func311([222,2356,0,1,1234]))
    print(func311([9090,2356,0,1,1234]))
    print(func311([10,2356,0,1,1234]))

    print("=======func312======")
    print(func312([7,0,7,8]))
    print(func312([3,0,7,8]))
    print(func312([1,9,7,4,3]))
    print(func312([2]))
    print(func312([59, 48, 11, 88, 64, 56]))
    print(func312([74, 42, 79, 92]))
    print(func312([50, 46, 18, 46, 88, 62]))
    print(func312([30, 48, 46, 45, 61]))
    print(func312([67]))
    print(func312([19, 60, 24, 25, 51, 76]))
    print(func312([22, 73, 7, 70, 89]))
    print(func312([51, 86, 84, 97, 70, 9, 67]))
    print(func312([76, 65, 29, 71, 58]))
    print(func312([10, 41, 67, 45, 97, 1, 9]))

    print("=======func313======")
    print(func313([[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16]]))
    print(func313([[1,2],[3,4]]))
    print(func313([[0,0],[1,1]]))
    print(func313([[1,2,3],[4,5,6],[7,8,9]]))
    print(func313([['1','2','3'],["4","5","6"],[7,8,9]]))
    print(func313([['a','b','c'],["D","E","F"],["H","I","J"]]))
    print(func313([[1,1,1],[10,10,10],[-1,-1,-1]]))
    print(func313([[0,0],[0,0]]))
    print(func313([["ab","12"],["ck","football"]]))
    print(func313([["ab",12],["ck","football"]]))

    print("=======func314======")
    print(func314([102,201,111,4]))
    print(func314([102,201,111,120]))
    print(func314([102]))
    print(func314([102,201]))
    print(func314([102,201,111]))
    print(func314([102,201,111,4,9090]))
    print(func314([102,201,111,4,4,31]))
    print(func314([102,201,111,4,99,31]))
    print(func314([102,201,111,1112]))
    print(func314([102,201,111,1234]))
    print(func314([102,201,111,78,87]))
    print(func314([102,201,111,78,618]))

    print("=======func315======")
    print(func315([1,2,4,5],3))
    print(func315([1,2,4,5],6))
    print(func315([1,2,4,5],5))
    print(func315([1,2,4,5],1))
    print(func315([1],1))
    print(func315([1],2))
    print(func315([1,2,3],2))
    print(func315([1,2,2,2],2))
    print(func315([1,2,2,2],1))
    print(func315([1,2,2,2],6))
'''