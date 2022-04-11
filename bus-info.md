# 버스 도착 정보 조회 및 저장

데이터를 주기적으로 가져오는 동작을 예제로 보여주기 위하여 센터필드 정류장에 대한 버스정보를 읽는 동작을 구현하고자 합니다.


## 경기버스 API

[경기버스정보](http://www.gbis.go.kr/gbis2014/publicService.action?cmd=mBusArrivalStation)에서 버스에 대한 정보를 조회 할 수 있습니다.

센터필드 정류장에 대한 조회 동작은 아래와 같습니다. 

http://openapi.gbis.go.kr/ws/rest/busstationservice?serviceKey=1234567890&keyword=%EC%84%BC%ED%84%B0%ED%95%84%EB%93%9C

![image](https://user-images.githubusercontent.com/52392004/162731065-7540a7f3-2f67-46e2-bd85-6b154c31c72d.png)

여기서 stationID에 대한 정보는 122000202임을 알 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/162731202-df75f3ec-aa99-4d82-ac2e-e42fcf86a86b.png)

센터필드역에 대한 버스 도착정보는 아래와 같이 확인이 가능합니다. 

http://openapi.gbis.go.kr/ws/rest/busarrivalservice/station?serviceKey=1234567890&stationId=122000202

![image](https://user-images.githubusercontent.com/52392004/162731386-b14e976f-457d-4743-a895-c275b882725c.png)

이때의 table에 대한 정보는 아래와 같습니다.

![image](https://user-images.githubusercontent.com/52392004/162731466-f5a09ff9-bb7b-447d-ab6d-34f918214a44.png)

여기서 reouteId 222000075에 대한가  
