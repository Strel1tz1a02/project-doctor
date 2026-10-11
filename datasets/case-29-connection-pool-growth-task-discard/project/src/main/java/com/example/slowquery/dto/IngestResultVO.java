package com.example.slowquery.dto;

import lombok.Data;

@Data
public class IngestResultVO {
    private int workers;
    private int success;
    private int timedOut;
    private int failed;
    private long elapsedMs;
    private int allocated;
    private int maxSize;
}
