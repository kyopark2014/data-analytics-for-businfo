const request = require('request');
const convert = require('xml-js');

const aws = require('aws-sdk');
const dynamo = new aws.DynamoDB.DocumentClient();

const tableName = process.env.tableName; 
const stationId = '122000202';

exports.handler = async (event) => {
    console.log('## ENVIRONMENT VARIABLES: ' + JSON.stringify(process.env));
    console.log('## EVENT: ' + JSON.stringify(event));

    let statusCode;
    let isCompleted = false;
    let predictTime="", plateNo="", remainSeatCnt="", routeId="";        

    const date = new Date();        
    let timestamp = Math.floor(date.getTime()/1000).toString();

    let arrivalInfo = [];

    try {
        // Get bus location infomation in Centerfield
        const params = { 
            uri: 'http://openapi.gbis.go.kr/ws/rest/busarrivalservice/station', 
            method: 'GET',
            qs:{ 
                serviceKey: '1234567890', // default
                stationId: stationId,
            },
        };
        makeRequest(params, function(responseCode, json){            
            if(responseCode==200) {
                var res = JSON.parse(json);
                console.log('json: '+JSON.stringify(res.response));

                if(res.response.msgHeader.resultCode._text == '0') { // Success
                    const list = res.response.msgBody.busArrivalList;

                    for(let i=0;i<list.length;i++) {
                        predictTime = list[i].predictTime1._text;
                        plateNo = list[i].plateNo1._text;
                        remainSeatCnt =  list[i].remainSeatCnt1._text;
                        routeId = list[i].routeId._text;
                        
                        console.log('RouteId: '+routeId+', No: '+plateNo+', predictTime: '+predictTime+', remainSeatCnt: '+remainSeatCnt);

                        // Get BusNumber
                        const busInfo = {
                            Timestamp: timestamp,
                            RouteId: routeId,
                            PlateNo: plateNo,
                            PredictTime: predictTime,
                            RemainSeatCnt: remainSeatCnt    
                        }
                        arrivalInfo.push(busInfo);                  
                        
                        // putItem to DynamoDB
                        var putParams = {
                            TableName: tableName,
                            Item: {
                                Timestamp: timestamp,
                                RouteId: routeId,
                                PlateNo: plateNo,
                                PredictTime: predictTime,
                                RemainSeatCnt: remainSeatCnt    
                            } 
                        };

                        dynamo.put(putParams, function(err){
                            if (err) {
                                console.log('Failure: '+err);
                            } 
                        });
                    }

                    // save arrivalInfo to dynamoDB
                    for(let i=0;i<arrivalInfo.length;i++) {
                        console.log('arrivalInfo['+i+']: '+JSON.stringify(arrivalInfo[i]));
                    } 
                    isCompleted = true;
                }
                else { // Success but no bus
                    statusCode = '404';
                    console.log(statusCode+': '+res.response.msgHeader.resultMessage._text);

                    isCompleted = true;
                } 
            }
            else { // Failure to request
                statusCode = responseCode;
                console.log(statusCode+': '+responseCode);

                isCompleted = true;
            }
        });        
    } catch(err) {
        console.log(err);
    };

    function wait(){
        return new Promise((resolve, reject) => {
          if(!isCompleted) {
            setTimeout(() => resolve("wait..."), 1000)
          }
          else {
            setTimeout(() => resolve("wait..."), 0)
          }
        });
    }
    console.log(await wait());
    console.log(await wait());
    console.log(await wait());
    console.log(await wait());
    console.log(await wait());
    
    const response = {
        statusCode: statusCode,
        result: JSON.stringify(arrivalInfo)
    };
    return response
}

function makeRequest(options, callback) {
    request(options, function (error, response, body) { 
        let statusCode = response.statusCode;
        if(!error && statusCode==200) {
            // console.log('response: '+JSON.stringify(response));

            statusCode = response.statusCode;

            // console.log('xml: '+body);
            var json = convert.xml2json(body, {compact: true, spaces: 4});

            callback(statusCode,json);
        }
        else {
            console.log('error: '+error);
            
            callback(statusCode,"");
        }
    });
}