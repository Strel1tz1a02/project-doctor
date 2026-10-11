package com.example.slowquery.dto;

import lombok.Data;

import java.util.Map;

@Data
public class MetricsVO {
    private long totalEvents;
    private Map<String, Long> eventsByModel;
}
