package com.example.slowquery.model;

import lombok.Data;

@Data
public class AuditEvent {
    private Long id;
    private String actor;
    private String action;
    private Long occurredAtMs;
}
