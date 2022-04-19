# Lambda for businfo를 주기적으로 실행

1) Lambda for businfo를 Rule에 등록하여 Cron job 형태로 실행합니다. 

```c
$ aws events put-rule \
--name businfo-rule \
--schedule-expression 'rate(1 minute)'
```

2) 실행후 아래와 같은 결과가 보여집니다. 

![noname](https://user-images.githubusercontent.com/52392004/163911571-5df23c99-681f-4906-be5a-62ebe07c6651.png)


"aws events list-rules" 명령을 통해 아래와 같은 rule이 등록되어 있음을 확인합니다. 

```java
        {
            "Name": "businfo-rule",
            "Arn": "arn:aws:events:ap-northeast-2:677146750822:rule/businfo-rule",
            "State": "ENABLED",
            "ScheduleExpression": "rate(1 minute)",
            "EventBusName": "default"
        },
```

