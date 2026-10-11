package com.example.slowquery.model;

import lombok.Data;

@Data
public class Product {
    private long id;
    private long categoryId;
    private long brandId;
    private String name;
    private long createdAtMs;
}
