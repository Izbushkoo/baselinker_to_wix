from typing import List, Any

from pydantic import BaseModel, Field, field_validator, ConfigDict
import uuid


def generate_handle_id():
    return f"product_{uuid.uuid4()}"

class WixImportFileModel(BaseModel):

    model_config = ConfigDict(
        populate_by_name=True
    )
    handleId: str
    fieldType: str = Field(default="Product")
    name: str
    description: str
    productImageUrl: List[str] | str = Field(alias="images")
    collection: Any = Field(default="")
    sku: str
    ribbon: Any = Field(default="")
    price: float
    surcharge: Any = Field(default="")
    visible: str = Field(default="TRUE")
    discountMode: str = Field(default="PERCENT")
    discountValue: int | float = Field(default=0)
    inventory: int = Field(alias="stock")
    weight: float
    cost: Any = Field(default="")
    productOptionName1: Any = Field(default="")
    productOptionType1: Any = Field(default="")
    productOptionDescription1: Any = Field(default="")
    productOptionName2: Any = Field(default="")
    productOptionType2: Any = Field(default="")
    productOptionDescription2: Any = Field(default="")
    productOptionName3: Any = Field(default="")
    productOptionType3: Any = Field(default="")
    productOptionDescription3: Any = Field(default="")
    productOptionName4: Any = Field(default="")
    productOptionType4: Any = Field(default="")
    productOptionDescription4: Any = Field(default="")
    productOptionName5: Any = Field(default="")
    productOptionType5: Any = Field(default="")
    productOptionDescription5: Any = Field(default="")
    productOptionName6: Any = Field(default="")
    productOptionType6: Any = Field(default="")
    productOptionDescription: Any = Field(default="")
    additionalInfoTitle1: Any = Field(default="")
    additionalInfoDescription1: Any = Field(default="")
    additionalInfoTitle2: Any = Field(default="")
    additionalInfoDescription2: Any = Field(default="")
    additionalInfoTitle3: Any = Field(default="")
    additionalInfoDescription3: Any = Field(default="")
    additionalInfoTitle4: Any = Field(default="")
    additionalInfoDescription4: Any = Field(default="")
    additionalInfoTitle5: Any = Field(default="")
    additionalInfoDescription5: Any = Field(default="")
    additionalInfoTitle6: Any = Field(default="")
    additionalInfoDescription6: Any = Field(default="")
    customTextField1: Any = Field(default="")
    customTextCharLimit1: Any = Field(default="")
    customTextMandatory1: Any = Field(default="")
    customTextField2: Any = Field(default="")
    customTextCharLimit2: Any = Field(default="")
    customTextMandatory2: Any = Field(default="")
    brand: str = Field(default="")


    @field_validator('productImageUrl', mode="before")
    def join_list_into_string(cls, v):
        if isinstance(v, list):
            # Объединяем список в строку через точку с запятой
            return ";".join(v)
        return v


if __name__ == "__main__":
    my = WixImportFileModel(productImageUrl=["qwe", "sdfs"])
    print(my)