package com.example.slowquery.model;

import lombok.Data;

import java.time.LocalDateTime;

@Data
public class User {
    private Long id;
    private String email;
    private String name;
    private LocalDateTime createdAt;
}
