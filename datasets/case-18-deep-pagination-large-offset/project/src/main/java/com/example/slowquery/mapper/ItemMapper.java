package com.example.slowquery.mapper;

import com.example.slowquery.model.Item;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ItemMapper {

    @Select(
        "SELECT * FROM items " +
        "ORDER BY id " +
        "LIMIT #{limit} OFFSET #{offset}"
    )
    List<Item> findItemsByOffset(@Param("limit") int limit, @Param("offset") int offset);

    @Select("SELECT COUNT(*) FROM items")
    long countItems();
}
