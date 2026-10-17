# 软件系统功能规格说明书：课码 (CodeClass)

## 1. 系统角色 (Actor)
* **学生**：提交 Python 代码作业，查看批改结果、薄弱项分析及学习建议。
* **教师/助教**：发布作业任务，查看班级整体提交情况、学生共性薄弱点。
* **系统管理员**：管理系统用户，配置知识图谱节点，监控大模型 API 调用状态与系统日志。

## 2. 功能树 (Feature Tree)
* **作业提交与管理模块**
  * FR-1.1：支持学生上传单文件或多文件的 `.py` 代码，并选择对应作业任务。
  * FR-1.2：支持多次提交，系统保留历史提交版本，允许学生对比前后代码差异。
  * FR-1.3：提供代码格式化检测（如是否符合 PEP 8 规范）。
* **智能批改与诊断模块**
  * FR-2.1：调用代码执行引擎运行提交的代码，通过预设测试用例进行正确性验证。
  * FR-2.2：利用大模型分析代码 AST（抽象语法树）和报错日志，定位具体错误行与逻辑漏洞。
  * FR-2.3：基于知识图谱，匹配代码错误对应的前置知识点（如：列表越界、作用域错误）。
* **反馈与学习辅助模块**
  * FR-3.1：生成自然语言的“启发式”批改反馈，不直接提供完整源码，而是提供修改思路和提示。
  * FR-3.2：生成个人“薄弱项雷达图”，向学生展示近期频繁出错的知识点。
  * FR-3.3：针对薄弱知识点，自动从题库中推荐 1-3 道相似练习题以供巩固。
* **教师管理模块**
  * FR-4.1：支持教师发布作业（上传题目描述、测试用例文件）。
  * FR-4.2：生成班级作业统计报表，展示平均分、高频错题及班级共性薄弱项。

## 3. 领域模型 (Domain Model UML)
[在此处插入 Mermaid 类图，建议在 Typora 或 GitHub 中预览]

```mermaid
classDiagram
    class User {
        +String username
        +String password
        +String role
        +login()
        +logout()
    }
    class Student {
        +String student_id
        +submit_assignment()
        +view_feedback()
    }
    class Teacher {
        +String teacher_id
        +create_assignment()
        +view_class_report()
    }
    class Assignment {
        +String title
        +String description
        +Date deadline
        +get_test_cases()
    }
    class Submission {
        +String code_content
        +DateTime submit_time
        +String status
        +run_tests()
        +analyze_code()
    }
    class Feedback {
        +String error_location
        +String knowledge_point
        +String suggestion
        +generate_suggestion()
    }
    class KnowledgeGraph {
        +String node_name
        +List~String~ relations
        +query_weakness()
    }

    User <|-- Student
    User <|-- Teacher
    Teacher "1" --> "*" Assignment : creates
    Student "1" --> "*" Submission : submits
    Assignment "1" --> "*" Submission : contains
    Submission "1" --> "1" Feedback : generates
    Feedback "*" --> "1" KnowledgeGraph : references