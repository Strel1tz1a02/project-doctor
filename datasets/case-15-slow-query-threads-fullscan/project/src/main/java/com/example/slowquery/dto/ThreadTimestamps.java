package com.example.slowquery.dto;

import lombok.Data;

@Data
public class ThreadTimestamps {
    private Long maxUpdatedAtMs;
    private Long maxRecencyAtMs;
}
