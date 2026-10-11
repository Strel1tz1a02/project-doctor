package com.example.slowquery.model;

import lombok.Data;

@Data
public class Section {
    private long id;
    private long courseId;
    private String title;
    private long createdAtMs;
}
