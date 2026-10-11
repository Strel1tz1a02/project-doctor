package com.example.slowquery.dto;

import lombok.Data;

@Data
public class BlockTripVO {
    private String tripId;
    private int blockSequence;
    private int stopCount;
}
