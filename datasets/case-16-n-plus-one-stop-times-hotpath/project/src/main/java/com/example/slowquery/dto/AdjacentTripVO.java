package com.example.slowquery.dto;

import lombok.Data;

@Data
public class AdjacentTripVO {
    private String tripId;
    private String blockId;
    private int stopCount;
    private String previousTripId;
    private String nextTripId;
}
