package com.example.slowquery.model;

import lombok.Data;

@Data
public class ExportRow {
    private long id;
    private String segment;
    private long amount;
    private long createdAtMs;
}
