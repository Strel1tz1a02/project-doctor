package com.example.slowquery.model;

import lombok.Data;

@Data
public class Job {
    private Long jobId;
    private String runId;
    private String jobName;
    private Long createdAtMs;
}
