# -*- coding: utf-8 -*-
"""标准答案（gold.py）：每个函数即为一道题。"""

def func0101(c):
    return round(c * 9 / 5 + 32, 2)

def func0102(n):
    return sum(int(d) for d in str(n))

def func0103(n):
    h, m, s = n // 3600, n % 3600 // 60, n % 60
    return f"{h:02d}:{m:02d}:{s:02d}"

def func0104(a, b):
    return [round(a / b, 2), a // b, a % b]

def func0201(n):
    return bin(n).count("1")

def func0202(n):
    a, b, c = n // 100, n // 10 % 10, n % 10
    return c * 100 + b * 10 + a

def func0203(a, b):
    return [a & b, a | b, a ^ b]

def func0301(s):
    return [sum(1 for ch in s if ch.isalpha()), sum(1 for ch in s if ch.isdigit())]

def func0302(s):
    t = s.strip().lower()
    return "YES" if t == t[::-1] else "NO"

def func0303(s):
    words = s.split()
    return [len(words), max(words, key=len)]

def func0304(s):
    return [s.capitalize(), s.upper(), s.lower(), len(s)]

def func0401(nums):
    return [max(nums), min(nums), round(sum(nums) / len(nums), 2)]

def func0402(nums):
    return [nums[::-1], nums[::2], nums[:3], nums[-2:]]

def func0403(nums):
    arr = list(nums)
    for i in range(len(arr) - 1):
        for j in range(len(arr) - 1 - i):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr

def func0404(nums):
    res = []
    for x in nums:
        if x not in res:
            res.append(x)
    return res

def func0501(words):
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    best = min(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return [best[0], best[1]]

def func0502(records):
    total = 0
    best_name, best_score = "", -1
    for name, score in records:
        total += score
        if score > best_score:
            best_name, best_score = name, score
    return [round(total / len(records), 2), best_name]

def func0503(a, b):
    sa, sb = set(a), set(b)
    return [sorted(sa & sb), sorted(sa | sb), sorted(sa - sb)]

def func0504(records):
    rows = sorted(records, key=lambda r: (-r[1], r[0]))
    return [r[0] for r in rows]

def func0601(score):
    if score >= 90:
        return "A"
    elif score >= 80:
        return "B"
    elif score >= 70:
        return "C"
    elif score >= 60:
        return "D"
    return "E"

def func0602(m, n):
    res = [str(x) for x in range(m, n + 1) if sum(int(d) ** 3 for d in str(x)) == x]
    return " ".join(res) if res else "none"

def func0603(n):
    cnt = 0
    for x in range(2, n + 1):
        ok = True
        for d in range(2, int(x ** 0.5) + 1):
            if x % d == 0:
                ok = False
                break
        if ok:
            cnt += 1
    return cnt

def func0604(n):
    return sum(i for i in range(1, n + 1) if i % 3 == 0 and i % 5 != 0)

def func0701(r, pi=3.14159):
    return round(pi * r * r, 2)

def func0702(a, b):
    return [a // b, a % b]

def func0703(nums):
    uniq = sorted(set(nums), reverse=True)
    if len(uniq) == 1:
        return [uniq[0], uniq[0]]
    return [uniq[0], uniq[1]]

def func0704(data):
    return ", ".join(f"{k}={v}" for k, v in data.items())

def func0801(n):
    if n <= 1:
        return 1
    return n * func0801(n - 1)

def func0802(n):
    if n <= 2:
        return 1
    return func0802(n - 1) + func0802(n - 2)

def func0803(a, b):
    if b == 0:
        return a
    return func0803(b, a % b)

def func0901(n):
    return [x * x for x in range(1, n + 1) if x % 2 == 0]

def func0902(s):
    return {ch: s.count(ch) for ch in s}

def func0903(n):
    return sum(i * i for i in range(1, n + 1) if i % 3 == 0)

def func0904(nums):
    return list(map(lambda x: x * 2, filter(lambda x: x % 3 == 0, nums)))

def func1001(a, b):
    try:
        x, y = int(a), int(b)
    except (TypeError, ValueError):
        return "输入格式错误"
    try:
        return round(x / y, 2)
    except ZeroDivisionError:
        return "除数不能为0"

def func1002(items):
    total, cnt, skip = 0.0, 0, 0
    for t in items:
        try:
            total += float(t)
            cnt += 1
        except (TypeError, ValueError):
            skip += 1
    if cnt == 0:
        return [0.0, skip]
    return [round(total / cnt, 2), skip]

class AgeError(Exception):
    """年龄不合法时抛出的自定义异常。"""

def func1003(age):
    if isinstance(age, bool) or not isinstance(age, int):
        return "错误:输入不是整数"
    try:
        if age < 0 or age > 150:
            raise AgeError("年龄不合法")
    except AgeError as exc:
        return f"错误:{exc}"
    return f"有效年龄:{age}"

def func1101(records):
    order, totals = [], {}
    for name, subject, score in records:
        if name not in totals:
            totals[name] = 0
            order.append(name)
        totals[name] += score
    return [[name, totals[name]] for name in order]

def func1102(lines):
    text = "\n".join(lines)
    return [len(lines), len(text.split()), len(text)]

def func1103(records):
    rows = [r for r in records if r[1] >= 60]
    rows.sort(key=lambda r: (-r[1], r[0]))
    return [r[0] for r in rows]

class Rectangle:
    def __init__(self, w, h):
        self.w = w
        self.h = h

    def area(self):
        return self.w * self.h

    def perimeter(self):
        return 2 * (self.w + self.h)

def func1201(w, h):
    r = Rectangle(w, h)
    return [r.area(), r.perimeter()]

class Student:
    def __init__(self, name, score):
        self.name = name
        self.score = score

    def __str__(self):
        return f"Student({self.name},{self.score})"

def func1202(name, score):
    return str(Student(name, score))

class Animal:
    def speak(self):
        return "..."


class Dog(Animal):
    def speak(self):
        return "Woof"


class Cat(Animal):
    def speak(self):
        return "Meow"

def func1203(kind):
    cls = {"dog": Dog, "cat": Cat}.get(str(kind).strip().lower(), Animal)
    return cls().speak()

class Account:
    def __init__(self, balance=0):
        self.balance = balance

    def deposit(self, amount):
        self.balance += amount

    def withdraw(self, amount):
        if amount > self.balance:
            return False
        self.balance -= amount
        return True

def func1204(balance, ops):
    acc = Account(balance)
    fails = 0
    for op, amount in ops:
        if op == "d":
            acc.deposit(amount)
        elif not acc.withdraw(amount):
            fails += 1
    return [acc.balance, fails]

if __name__ == "__main__":
    pass
