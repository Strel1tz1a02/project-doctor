package com.example.slowquery.model;

import lombok.Data;

@Data
public class JobStep {
    private Long stepId;
    private Long jobId;
    private String stepName;
    private Integer stepOrder;
}
