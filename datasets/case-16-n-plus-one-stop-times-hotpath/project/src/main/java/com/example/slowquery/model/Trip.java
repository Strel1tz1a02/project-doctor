package com.example.slowquery.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Trip {
    private String tripId;
    private String blockId;
    private String routeId;
    private String serviceId;
    private String tripHeadsign;
    private LocalDateTime createdAt;
}
