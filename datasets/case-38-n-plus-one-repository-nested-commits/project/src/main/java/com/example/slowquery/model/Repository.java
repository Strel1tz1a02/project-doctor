package com.example.slowquery.model;

import lombok.Data;

@Data
public class Repository {
    private long id;
    private String owner;
    private String name;
    private long createdAtMs;
}
