# kinesis-data-stream
It shows an example 


## 데이터 입력 

여기서는 정기적으로 데이터가 들어오는 상황을 만들기 위하여, 경기버스 노선정보를 정기적으로 조회하여 Amazon DynamoDB에 저장하고자 합니다. [버스정보조회](https://github.com/kyopark2014/kinesis-data-stream/blob/main/bus-info.md) 에서 확인한 정류장 정보를 활용하여 아래에 대한 정보를 조회하고자 합니다.  

- 센터필드 정류장: stationId=122000202
- 검색하려는 노선 경로: routeId: routeID=222000074
- 해당 노선에서 센터필드 정류장의 순번: staOrder=81
- 노선번호: 1100

아래와 같이 검색할 수 있습니다. 

http://openapi.gbis.go.kr/ws/rest/busarrivalservice?serviceKey=1234567890&stationId=122000202&routeId=222000074&staOrder=81

상기 API를 통해 "경기74아3257" 버스가 12분후에 도착예정이며, 현재 43개의 좌석이 비어 있음을 알 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/162734910-16d8b31f-3ffd-428d-85d4-ce63a818c040.png)




![image](https://user-images.githubusercontent.com/52392004/162723697-f807b59b-2577-4a0a-90be-6477f7d2953c.png)
