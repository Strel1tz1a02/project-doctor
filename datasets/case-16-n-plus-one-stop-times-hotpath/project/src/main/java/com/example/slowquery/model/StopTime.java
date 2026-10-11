package com.example.slowquery.model;

import lombok.Data;

@Data
public class StopTime {
    private String tripId;
    private Integer stopSequence;
    private String stopId;
    private String arrivalTime;
    private String departureTime;
}
