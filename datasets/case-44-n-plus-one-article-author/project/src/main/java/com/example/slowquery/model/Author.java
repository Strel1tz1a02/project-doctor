package com.example.slowquery.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class Author {
    private Long id;
    private String name;
    private String email;
    private LocalDateTime createdAt;
}
