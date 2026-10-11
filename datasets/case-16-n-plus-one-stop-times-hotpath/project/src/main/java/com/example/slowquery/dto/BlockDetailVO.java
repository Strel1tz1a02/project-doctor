package com.example.slowquery.dto;

import lombok.Data;

import java.util.List;

@Data
public class BlockDetailVO {
    private List<AdjacentTripVO> adjacentTrips;
    private List<BlockTripVO> blockSequences;
}
