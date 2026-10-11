package com.example.slowquery.model;

import lombok.Data;

@Data
public class JobLog {
    private Long logId;
    private Long jobId;
    private String level;
    private String message;
    private Long createdAtMs;
}
