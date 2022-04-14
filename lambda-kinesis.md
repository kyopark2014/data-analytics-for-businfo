# Lambda for Kinesis

## Kinesis stream data

Kinesis stream은 DynamoDB의 변경 event를 아래와 같은 포맷으로 받습니다. 

```java
{
    "Records": [
        {
            "kinesis": {
                "kinesisSchemaVersion": "1.0",
                "partitionKey": "F56FB2F544F0BF6834E95F61F91C692D",
                "sequenceNumber": "49628566489609057616651776916055991431846499866048987154",
                "data": "eyJhd3NSZWdpb24iOiJhcC1ub3J0aGVhc3QtMiIsImV2ZW50SUQiOiJlZmMwZWVkOC1iMWNlLTRiODktOTI1Mi1hYmQzNmVkNmExYTYiLCJldmVudE5hbWUiOiJJTlNFUlQiLCJ1c2VySWRlbnRpdHkiOm51bGwsInJlY29yZEZvcm1hdCI6ImFwcGxpY2F0aW9uL2pzb24iLCJ0YWJsZU5hbWUiOiJkeW5hbW9kYi1idXNpbmZvIiwiZHluYW1vZGIiOnsiQXBwcm94aW1hdGVDcmVhdGlvbkRhdGVUaW1lIjoxNjQ5OTMxMjQ4NzQwLCJLZXlzIjp7IlRpbWVzdGFtcCI6eyJTIjoiMTY0OTkzMTI0OCJ9LCJSb3V0ZUlkIjp7IlMiOiIyMjcwMDAwMTkifX0sIk5ld0ltYWdlIjp7IlJlbWFpblNlYXRDbnQiOnsiUyI6IjM3In0sIlRpbWVzdGFtcCI6eyJTIjoiMTY0OTkzMTI0OCJ9LCJQbGF0ZU5vIjp7IlMiOiLqsr3quLA3NeyekDg1MDUifSwiUm91dGVJZCI6eyJTIjoiMjI3MDAwMDE5In0sIlByZWRpY3RUaW1lIjp7IlMiOiI3In19LCJTaXplQnl0ZXMiOjExOX0sImV2ZW50U291cmNlIjoiYXdzOmR5bmFtb2RiIn0=",
                "approximateArrivalTimestamp": 1649931249.337
            },
            "eventSource": "aws:kinesis",
            "eventVersion": "1.0",
            "eventID": "shardId-000000000001:49628566489609057616651776916055991431846499866048987154",
            "eventName": "aws:kinesis:record",
            "invokeIdentityArn": "arn:aws:iam::xxxx:role/service-role/lambda-for-kinesis-role-6wb2ydbv",
            "awsRegion": "ap-northeast-2",
            "eventSourceARN": "arn:aws:kinesis:ap-northeast-2:xxxx:stream/businfo"
        }
    ]
}
```

## Event parsing

Kinesis stream에서 전달하는 event에서 data를 추출하여 아래와 같이 base64로 decoding 합니다.

```java
    console.log('event: '+JSON.stringify((event)));
    
    let records = event["Records"];
    let eventInfo = [];
    records.forEach((record) => {
        let body = Buffer.from(record['kinesis']['data'], 'base64');
        
        eventInfo.push(JSON.parse(body));
    });
    
    console.log('eventInfo: %j', eventInfo);    
```

decording후 결과는 아래와 같습니다. 

```java
{
    "awsRegion": "ap-northeast-2",
    "eventID": "efc0eed8-b1ce-4b89-9252-abd36ed6a1a6",
    "eventName": "INSERT",
    "userIdentity": null,
    "recordFormat": "application/json",
    "tableName": "dynamodb-businfo",
    "dynamodb": {
        "ApproximateCreationDateTime": 1649931248740,
        "Keys": {
            "Timestamp": {
                "S": "1649931248"
            },
            "RouteId": {
                "S": "227000019"
            }
        },
        "NewImage": {
            "RemainSeatCnt": {
                "S": "37"
            },
            "Timestamp": {
                "S": "1649931248"
            },
            "PlateNo": {
                "S": "경기75자8505"
            },
            "RouteId": {
                "S": "227000019"
            },
            "PredictTime": {
                "S": "7"
            }
        },
        "SizeBytes": 119
    },
    "eventSource": "aws:dynamodb"
}
```

## Repository

Lambda for Kinesis의 소스코드는 cdk의 repository에 있으며 URL은 아래와 같습니다. 

https://github.com/kyopark2014/kinesis-data-stream/tree/main/cdk/repositories/get-kinesisinfo
