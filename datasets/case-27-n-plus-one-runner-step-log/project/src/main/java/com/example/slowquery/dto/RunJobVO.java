package com.example.slowquery.dto;

import lombok.Data;

@Data
public class RunJobVO {
    private Long jobId;
    private String jobName;
    private int stepCount;
}
