package com.example.slowquery.model;

import lombok.Data;

@Data
public class AuditLog {
    private Long id;
    private String serviceName;
    private String level;
    private String message;
    private String traceId;
    private Long createdAtMs;
}
