# Lambda for Firehose

## Firehose Data

```java
{
    "invocationId": "03e5bd3b-848c-4b86-a88b-e7a000b48125",
    "sourceKinesisStreamArn": "arn:aws:kinesis:ap-northeast-2:677146750822:stream/businfo",
    "deliveryStreamArn": "arn:aws:firehose:ap-northeast-2:677146750822:deliverystream/CdkStack-FirehoseDeliveryStream-bgNdr6G4QDWq",
    "region": "ap-northeast-2",
    "records": [
        {
            "recordId": "49628654765235663403446902955224362712470206619186102290000000",
            "approximateArrivalTimestamp": 1650162905387,
            "data": "eyJhd3NSZWdpb24iOiJhcC1ub3J0aGVhc3QtMiIsImV2ZW50SUQiOiJiZTkwMTkyYy0xMGFmLTQ4OWQtYTg4Ny0yYzJhMGVkY2VjMjMiLCJldmVudE5hbWUiOiJJTlNFUlQiLCJ1c2VySWRlbnRpdHkiOm51bGwsInJlY29yZEZvcm1hdCI6ImFwcGxpY2F0aW9uL2pzb24iLCJ0YWJsZU5hbWUiOiJkeW5hbW9kYi1idXNpbmZvIiwiZHluYW1vZGIiOnsiQXBwcm94aW1hdGVDcmVhdGlvbkRhdGVUaW1lIjoxNjUwMTYyOTA1MjY5LCJLZXlzIjp7IlRpbWVzdGFtcCI6eyJTIjoiMTY1MDE2MjkwNSJ9LCJSb3V0ZUlkIjp7IlMiOiIyMjcwMDAwMTkifX0sIk5ld0ltYWdlIjp7IlJlbWFpblNlYXRDbnQiOnsiUyI6IjQ0In0sIlRpbWVzdGFtcCI6eyJTIjoiMTY1MDE2MjkwNSJ9LCJQbGF0ZU5vIjp7IlMiOiLqsr3quLA3NeyekDcwMDUifSwiUm91dGVJZCI6eyJTIjoiMjI3MDAwMDE5In0sIlByZWRpY3RUaW1lIjp7IlMiOiIyIn19LCJTaXplQnl0ZXMiOjExOX0sImV2ZW50U291cmNlIjoiYXdzOmR5bmFtb2RiIn0=",
            "kinesisRecordMetadata": {
                "sequenceNumber": "49628654765235663403446902955224362712470206619186102290",
                "subsequenceNumber": 0,
                "partitionKey": "0AB18464EFEE6043E48DD4475DABA453",
                "shardId": "shardId-000000000001",
                "approximateArrivalTimestamp": 1650162905387
            }
        },
```

여기서 "data"를 base64로 decoding한 결과는 아래와 같습니다. 
```java
{
    "awsRegion": "ap-northeast-2",
    "eventID": "8b29bf28-de2e-4171-b2cd-5dff8a131f3e",
    "eventName": "INSERT",
    "userIdentity": null,
    "recordFormat": "application/json",
    "tableName": "dynamodb-businfo",
    "dynamodb": {
        "ApproximateCreationDateTime": 1650163085569,
        "Keys": {
            "Timestamp": {
                "S": "1650163085"
            },
            "RouteId": {
                "S": "227000019"
            }
        },
        "NewImage": {
            "RemainSeatCnt": {
                "S": "29"
            },
            "Timestamp": {
                "S": "1650163085"
            },
            "PlateNo": {
                "S": "경기75자7007"
            },
            "RouteId": {
                "S": "227000019"
            },
            "PredictTime": {
                "S": "52"
            }
        },
        "SizeBytes": 120
    },
    "eventSource": "aws:dynamodb"
}
```

이 데이터는 dynamodb에서 INSERT시 발생한 event로 실제 사용할 데이터에 비해 redundant하므로, 아래와 같은 포맷으로 변경하고자 합니다. 


        
