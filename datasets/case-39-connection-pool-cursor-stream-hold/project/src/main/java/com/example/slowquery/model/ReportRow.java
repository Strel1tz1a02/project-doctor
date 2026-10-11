package com.example.slowquery.model;

import lombok.Data;

@Data
public class ReportRow {
    private long id;
    private String region;
    private String metric;
    private long amount;
    private long createdAtMs;
}
