package com.example.slowquery.model;

import lombok.Data;

@Data
public class Article {
    private Long id;
    private String title;
    private String content;
    private Long publishedAtMs;
}
