package com.example.slowquery.mapper;

import com.example.slowquery.model.Product;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ProductMapper {

    @Select("SELECT id, category_id, brand_id, name, created_at_ms FROM products ORDER BY created_at_ms DESC LIMIT #{size}")
    List<Product> findRecentProducts(@Param("size") int size);

    @Select("SELECT name FROM categories WHERE id = #{categoryId}")
    String findCategoryNameById(@Param("categoryId") long categoryId);

    @Select("SELECT name FROM brands WHERE id = #{brandId}")
    String findBrandNameById(@Param("brandId") long brandId);
}
