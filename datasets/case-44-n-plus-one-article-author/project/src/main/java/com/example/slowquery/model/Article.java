package com.example.slowquery.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Article {
    private Long id;
    private Long authorId;
    private String title;
    private String status;
    private String summary;
    private LocalDateTime createdAt;
}
