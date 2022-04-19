# DynamoDB의 Event를 Kinesis Data Stream으로 전송

1) Kinesis Data Stream에 대한 Console로 이동합니다. 

https://ap-northeast-2.console.aws.amazon.com/dynamodbv2/home?region=ap-northeast-2#tables

2) [Tables]에서 "businfo"를 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163906855-c6765ad5-2305-45bd-9c97-387e47fe28ec.png)

3) [businfo]에서 아래와 같이 [Exports and streams]를 선택 후, [Amazon Kinesis data stream details]에서 [Enable]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163907197-32230771-6dcd-4e7e-863e-258e067252a9.png)

4) [Stream to an Amazon Kinesis data stream]에서 [Destination Kinesis data stream]에서 "kinesis-businfo"를 선택하고, [Enable stream]을 선택합니다. 

![noname](https://user-images.githubusercontent.com/52392004/163907402-04fe1f9d-6ef6-498f-95c5-4120cb1ac9d7.png)

5) 아래와 같이 "kinesis-businfo"가 DynamoDB의 event를 stream으로 수신하도록 설정된것을 확인 할 수 있습니다. 

![image](https://user-images.githubusercontent.com/52392004/163907522-0f1df974-70aa-476b-bfec-24cfaa37cf3c.png)
