package com.example.slowquery.model;

import lombok.Data;

@Data
public class Article {
    private Long id;
    private String articleCode;
    private String title;
    private String authorCode;
    private Long createdAtMs;
}
