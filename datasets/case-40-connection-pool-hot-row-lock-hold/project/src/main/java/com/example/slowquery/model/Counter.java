package com.example.slowquery.model;

import lombok.Data;

@Data
public class Counter {
    private long id;
    private String counterKey;
    private long value;
    private long updatedAtMs;
}
