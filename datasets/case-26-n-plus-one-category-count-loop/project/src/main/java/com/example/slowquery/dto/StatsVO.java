package com.example.slowquery.dto;

import lombok.Data;

import java.util.Map;

@Data
public class StatsVO {
    private long totalOrders;
    private Map<String, Long> orderCountByCategory;
    private Map<String, Long> amountByCategory;
}
