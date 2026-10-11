package com.example.slowquery.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface OrderStatsMapper {

    @Select("SELECT COUNT(*) FROM orders")
    long countAll();

    @Select("SELECT DISTINCT category FROM orders ORDER BY category")
    List<String> findDistinctCategories();

    @Select("SELECT COUNT(*) FROM orders WHERE category = #{category}")
    long countByCategory(@Param("category") String category);

    @Select("SELECT COALESCE(SUM(amount), 0) FROM orders WHERE category = #{category}")
    long sumAmountByCategory(@Param("category") String category);
}
